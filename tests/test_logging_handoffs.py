# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Installed collaborators produce a usable trace and preserve numerical results."""

import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from epsm import Building, configure_logging, reset_logging

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_real_record_rc_lca_handoff(tmp_path, monkeypatch):
    from epsm_data import Catalogue
    from epsm_rc import simulate_building

    supported = all(
        "log_context" in inspect.signature(function).parameters
        for function in (Catalogue.load, simulate_building)
    )
    if not supported:
        if os.environ.get("EPSM_LOGGING_INTEGRATION") == "1":
            pytest.fail(
                "Coordinated logging integration requires the instrumented wheels"
            )
        pytest.skip(
            "Dedicated logging integration installs the coordinated wheel revisions"
        )
    monkeypatch.syspath_prepend(str(EXAMPLES))
    from logging_walkthrough import run

    result = run(tmp_path)
    saved = json.loads((tmp_path / "runs" / result.id / "evaluation.json").read_text())
    assert saved["id"] == result.id
    assert "logging-test" not in json.dumps(saved)


def test_worker_queue_has_one_writer_and_keeps_context(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(EXAMPLES / "logging_workers.py"),
            "--directory",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    records = [
        json.loads(line)
        for line in (tmp_path / "logs/study.jsonl").read_text().splitlines()
    ]
    assert len(records) == 1
    assert records[0]["context"]["study_id"] == "queue-example"
    assert not result.stderr


def test_handled_failure_has_one_traceback_and_reset(tmp_path):
    configure_logging(directory=tmp_path, console_level="OFF")
    try:
        with pytest.raises(ValueError):
            Building.empty().simulate(engine="unsupported", weather=None)
    finally:
        reset_logging()
    records = [
        json.loads(line)
        for line in (tmp_path / "logs/study.jsonl").read_text().splitlines()
    ]
    assert len([record for record in records if "exception" in record]) == 1
    assert records[-1]["event"] == "evaluation.failed"


def test_older_collaborator_signature_and_internal_typeerror():
    from epsm._logging import call_with_context

    def old(value):
        return value

    def new(value, *, log_context=None):
        raise TypeError("Calculation failed inside collaborator")

    assert call_with_context(old, 7, log_context={"study_id": "compatibility"}) == 7
    with pytest.raises(TypeError, match="inside collaborator"):
        call_with_context(new, 7)


def test_verbosity_does_not_change_energy_or_physical_identity(tmp_path, monkeypatch):
    from importlib.resources import files

    from epsm_rc import simulate_building

    from epsm import Weather

    monkeypatch.syspath_prepend(str(EXAMPLES))
    from renovation_case import make_case, rc_settings

    building = make_case()["baseline"]
    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
    before = building.snapshot().sha256
    configure_logging(enabled=False)
    try:
        quiet = simulate_building(building, weather=weather, settings=rc_settings())
        configure_logging(directory=tmp_path, console_level="OFF")
        detailed = simulate_building(building, weather=weather, settings=rc_settings())
    finally:
        reset_logging()
    assert quiet.scalars == detailed.scalars
    assert quiet.run_id == detailed.run_id
    assert building.snapshot().sha256 == before
