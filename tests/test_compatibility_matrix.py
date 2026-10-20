"""Check the matrix command without installing or running platform packages."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "scripts" / "compatibility_matrix.py"


def run_matrix(tmp_path, manifest=None, *arguments):
    command = [sys.executable, str(COMMAND)]
    if manifest is not None:
        path = tmp_path / "combination.json"
        path.write_text(json.dumps(manifest))
        command.extend(["--manifest", str(path)])
    return subprocess.run(
        [*command, *arguments], cwd=tmp_path, text=True, capture_output=True
    )


def matrix_output(result):
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("matrix=")
    return json.loads(result.stdout.removeprefix("matrix="))


@pytest.fixture
def platform_manifest():
    return {
        "format": 1,
        "python": ["3.11", "3.13"],
        "packages": {
            "epsm_core": {"version": "1.2.3", "revision": "a" * 40},
            "epsm_data": {"version": "2.3.4", "revision": "b" * 40},
            "epsm": {"version": "3.4.5", "revision": "self"},
        },
    }


def test_routine_platform_runs_only_both_pinned_python_lanes(
    tmp_path, platform_manifest
):
    result = matrix_output(run_matrix(tmp_path, platform_manifest))
    assert result == {
        "include": [
            {
                "python": python,
                "mode": "pinned",
                "epsm_core": "a" * 40,
                "epsm_data": "b" * 40,
            }
            for python in ("3.11", "3.13")
        ]
    }


def test_explicit_main_mode_uses_one_lane_without_changing_pins(
    tmp_path, platform_manifest
):
    result = matrix_output(run_matrix(tmp_path, platform_manifest, "--mode", "main"))
    assert result == {
        "include": [
            {
                "python": "3.13",
                "mode": "main",
                "epsm_core": "main",
                "epsm_data": "main",
            }
        ]
    }
    assert json.loads((tmp_path / "combination.json").read_text()) == platform_manifest


def test_logging_manifest_supplies_checkout_pins_and_both_python_lanes(tmp_path):
    manifest = {
        "schema_version": 1,
        "packages": {"epsm_core": "c" * 40, "epsm_rc": "d" * 40},
    }
    result = matrix_output(run_matrix(tmp_path, manifest, "--mode", "pinned"))
    assert result == {
        "include": [
            {
                "python": python,
                "mode": "pinned",
                "epsm_core": "c" * 40,
                "epsm_rc": "d" * 40,
            }
            for python in ("3.11", "3.13")
        ]
    }


def test_default_manifest_is_found_outside_the_repository(tmp_path):
    result = matrix_output(run_matrix(tmp_path))
    expected = json.loads((ROOT / "compatibility.json").read_text())
    assert [row["python"] for row in result["include"]] == expected["python"]
    assert all(row["mode"] == "pinned" for row in result["include"])
    assert all("epsm" not in row for row in result["include"])


def test_development_branch_mode_is_not_accepted(tmp_path, platform_manifest):
    result = run_matrix(tmp_path, platform_manifest, "--mode", "dev")
    assert result.returncode != 0
    assert "invalid choice" in result.stderr
    assert "matrix=" not in result.stdout


def test_missing_package_revision_fails_before_emitting_matrix(tmp_path):
    result = run_matrix(
        tmp_path,
        {"python": ["3.11"], "packages": {"epsm_core": {"version": "1.2.3"}}},
    )
    assert result.returncode != 0
    assert "epsm_core" in result.stderr
    assert "revision" in result.stderr
    assert "matrix=" not in result.stdout
