# SPDX-License-Identifier: MIT
"""The complete-study gate retains missing prerequisites without false passes."""

import json
import subprocess
import sys
from pathlib import Path


def test_required_engine_fails_before_execution_and_preserves_earlier_evidence(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/check_study_platform.py"
    directory = tmp_path / "acceptance"
    command = [sys.executable, str(script), "--directory", str(directory),
               "--energyplus-exe", str(tmp_path / "missing-energyplus")]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    report = directory / "study-compatibility-report.json"
    evidence = json.loads(report.read_text())
    assert evidence["status"] == "failed"
    assert "EnergyPlus prerequisite" in evidence["failure"]["message"]
    assert evidence["planned_evaluations"] == 6
    assert not (directory / "execution").exists()
    original = report.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert report.read_bytes() == original
