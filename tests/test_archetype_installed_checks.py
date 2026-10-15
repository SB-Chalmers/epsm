"""Installed acceptance checks fail visibly when required evidence is missing."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def checker():
    path = Path(__file__).resolve().parents[1] / "scripts/check_archetype_handoff.py"
    spec = importlib.util.spec_from_file_location("check_archetype_handoff", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_missing_energyplus_is_a_failed_prerequisite(checker, tmp_path):
    with pytest.raises(RuntimeError, match="EnergyPlus prerequisite"):
        checker.require_energyplus(tmp_path / "missing-energyplus")


def test_missing_revision_receipt_is_a_failed_prerequisite(checker, tmp_path):
    with pytest.raises(RuntimeError, match="revision receipt"):
        checker.read_receipt(tmp_path / "missing-receipt.json")


def test_receipt_rejects_moving_refs_and_missing_packages(checker, tmp_path):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(
        json.dumps({"packages": {"epsm": {"revision": "dev", "version": "0.2.0"}}})
    )
    with pytest.raises(RuntimeError, match="exact revisions"):
        checker.read_receipt(receipt)


def test_exact_receipt_is_retained_for_installed_results(checker, tmp_path):
    packages = {
        name: {"revision": "a" * 40, "version": "0.1.0"}
        for name in checker.REQUIRED_PACKAGES
    }
    evidence = {"format": 1, "mode": "pinned", "python": "3.12.3", "packages": packages}
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(evidence))
    assert checker.read_receipt(receipt) == evidence


def test_command_retains_failed_prerequisite_evidence(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/check_archetype_handoff.py"
    output = tmp_path / "output"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--directory",
            str(output),
            "--energyplus-exe",
            str(tmp_path / "missing-energyplus"),
            "--compatibility-receipt",
            str(tmp_path / "missing-receipt"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    evidence = json.loads((output / "archetype-compatibility-report.json").read_text())
    assert evidence["status"] == "failed"
    assert evidence["failure"]["type"] == "RuntimeError"
    assert "EnergyPlus prerequisite" in evidence["failure"]["message"]
