# SPDX-License-Identifier: MIT
"""The complete-study gate retains missing prerequisites without false passes."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def test_retained_baseline_has_known_zero_embodied_impact_but_changes_need_contributions():
    """Retaining inventory creates no installation event in this assessment."""
    import pytest

    script = Path(__file__).resolve().parents[1] / "scripts/check_study_platform.py"
    spec = importlib.util.spec_from_file_location("study_platform_check", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline = {
        "status": "complete",
        "material_gwp_kgco2e": 0.0,
        "assessment": {"baseline": "retained"},
        "contributions": [{"module": "B6"}],
    }
    module.check_material_assessment(baseline, is_baseline=True)
    with pytest.raises(RuntimeError, match="Embodied"):
        module.check_material_assessment(baseline, is_baseline=False)
    with pytest.raises(RuntimeError, match="Embodied"):
        module.check_material_assessment(
            {**baseline, "material_gwp_kgco2e": None}, is_baseline=True
        )
    replacement = {
        **baseline,
        "material_gwp_kgco2e": 120.0,
        "contributions": [{"module": "A1A3"}, {"module": "B6"}],
    }
    module.check_material_assessment(replacement, is_baseline=False)


def test_required_engine_fails_before_execution_and_preserves_earlier_evidence(
    tmp_path,
):
    script = Path(__file__).resolve().parents[1] / "scripts/check_study_platform.py"
    directory = tmp_path / "acceptance"
    command = [
        sys.executable,
        str(script),
        "--directory",
        str(directory),
        "--energyplus-exe",
        str(tmp_path / "missing-energyplus"),
    ]
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
