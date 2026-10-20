# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Installed workflow acceptance rejects incomplete rows and retains failed gates."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def checker(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/check_workflow_handoff.py"
    # These are acceptance helpers from this same checkout, never sibling science packages.
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("check_workflow_handoff", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_receipt_requires_workflows_and_exact_source_revisions(checker, tmp_path):
    path = tmp_path / "receipt.json"
    packages = {
        name: {"version": "0.3.0", "revision": "a" * 40}
        for name in checker.REQUIRED_PACKAGES
    }
    path.write_text(json.dumps({"packages": packages}))
    assert checker.read_workflow_receipt(path)["packages"] == packages
    del packages["epsm_workflows"]
    path.write_text(json.dumps({"packages": packages}))
    with pytest.raises(RuntimeError, match="epsm_workflows"):
        checker.read_workflow_receipt(path)
    packages["epsm_workflows"] = {"version": "0.3.0", "revision": "main"}
    path.write_text(json.dumps({"packages": packages}))
    with pytest.raises(RuntimeError, match="exact revisions"):
        checker.read_workflow_receipt(path)


@pytest.fixture
def retained_rows():
    from epsm import Building, EnergyResult, Evaluation

    building = Building(preset="illustrative-reference")
    state = building.snapshot()
    records = []
    for index, amount in enumerate((4.0, 2.0)):
        energy = EnergyResult(
            engine="unit-fixture",
            scalars={},
            hourly={},
            units={},
            diagnostics={"accepted": True},
            artifacts={},
            delivered_by_carrier={"electricity": amount},
        )
        evaluation = Evaluation(
            id=f"evaluation-{index}",
            engine="unit-fixture",
            energy_id=f"energy-{index}",
            state_id=state.sha256,
            snapshot=state.to_dict(),
            energy=energy.to_dict(),
        )
        records.append(
            {
                "index": index,
                "case_id": f"case-{index}",
                "status": "succeeded",
                "result": evaluation.to_dict(),
            }
        )
    return records, ["case-0", "case-1"], [state.sha256] * 2


def test_metrics_preserve_prepared_row_order(checker, retained_rows):
    rows, identities, states = retained_rows
    assert checker.metrics_from_rows(rows, identities, states) == [4.0, 2.0]


@pytest.mark.parametrize(
    "change,match",
    [
        ("missing", "successful result"),
        ("failed", "successful result"),
        ("order", "alignment"),
        ("state", "physical state"),
        ("annual", "annual"),
        ("accepted", "complete"),
        ("boundary", "boundary"),
    ],
)
def test_incomplete_or_misaligned_rows_cannot_become_sensitivity_inputs(
    checker, retained_rows, change, match
):
    rows, identities, states = retained_rows
    if change == "missing":
        rows[0] = None
    elif change == "failed":
        rows[0] = {
            "index": 0,
            "case_id": "case-0",
            "status": "failed",
            "error": {"message": "retained fault"},
        }
    elif change == "order":
        rows.reverse()
    elif change == "state":
        states[0] = "different-state"
    elif change == "annual":
        rows[0]["result"]["energy"]["annual"] = False
    elif change == "accepted":
        rows[0]["result"]["energy"]["diagnostics"]["accepted"] = False
    elif change == "boundary":
        rows[0]["result"]["energy"]["boundary"] = "different-boundary"
    with pytest.raises(ValueError, match=match):
        checker.metrics_from_rows(rows, identities, states)


def test_command_records_missing_prerequisite_and_preserves_existing_report(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/check_workflow_handoff.py"
    directory = tmp_path / "acceptance"
    command = [
        sys.executable,
        str(path),
        "--directory",
        str(directory),
        "--energyplus-exe",
        str(tmp_path / "missing-engine"),
        "--compatibility-receipt",
        str(tmp_path / "missing-receipt"),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    report = directory / "workflow-compatibility-report.json"
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "failed"
    assert "EnergyPlus prerequisite" in evidence["failure"]["message"]
    assert evidence["controlled_fault_injection"] is True
    original = report.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert report.read_bytes() == original
