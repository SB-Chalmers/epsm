# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
"""Check current compatibility documentation without rewriting historical evidence."""

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "scripts" / "render_compatibility.py"
START = "<!-- compatibility-table:start -->"
END = "<!-- compatibility-table:end -->"


@pytest.fixture
def repository(tmp_path):
    manifest = {
        "format": 1,
        "packages": {
            "epsm_data": {"version": "0.6.0", "revision": "a" * 40},
            "epsm": {"version": "0.3.0", "revision": "self"},
        },
    }
    (tmp_path / "compatibility.json").write_text(json.dumps(manifest))
    (tmp_path / "README.md").write_text(
        "# EPSM\n\nHistorical release: Data 0.5.0 at old-release.\n\n"
        f"{START}\nOld current table.\n{END}\n\n"
        "Keep this source note and historical version 0.1.0.\n"
    )
    return tmp_path


def render(repository, *arguments):
    return subprocess.run(
        [sys.executable, str(COMMAND), "--root", str(repository), *arguments],
        cwd=repository,
        text=True,
        capture_output=True,
    )


def test_render_preserves_history_and_uses_sorted_names_full_sha_and_self(repository):
    readme = repository / "README.md"
    before = readme.read_text()
    result = render(repository)
    assert result.returncode == 0, result.stderr
    after = readme.read_text()
    assert after.split(START)[0] == before.split(START)[0]
    assert after.split(END)[1] == before.split(END)[1]
    assert after.split(START)[1].split(END)[0] == (
        "\n| Package | Version | Tested commit |\n"
        "| --- | --- | --- |\n"
        "| `epsm` | 0.3.0 | `self` |\n"
        f"| `epsm_data` | 0.6.0 | `{'a' * 40}` |\n"
    )
    assert render(repository, "--check").returncode == 0


def test_check_reports_drift_without_changing_the_readme(repository):
    readme = repository / "README.md"
    before = readme.read_bytes()
    result = render(repository, "--check")
    assert result.returncode != 0
    assert "out of date" in result.stderr.lower()
    assert readme.read_bytes() == before


@pytest.mark.parametrize(
    "markers",
    [
        "No table markers.",
        f"{START}\nNo end.",
        f"{END}\n{START}",
        f"{START}\n{START}\n{END}",
    ],
)
def test_invalid_markers_fail_without_mutating_document(repository, markers):
    readme = repository / "README.md"
    readme.write_text(f"# EPSM\n\n{markers}\nHistorical text.\n")
    before = readme.read_bytes()
    for arguments in ((), ("--check",)):
        result = render(repository, *arguments)
        assert result.returncode != 0
        assert "marker" in result.stderr.lower()
        assert readme.read_bytes() == before


def test_manifest_version_change_updates_only_the_current_table(repository):
    assert render(repository).returncode == 0
    manifest_path = repository / "compatibility.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["packages"]["epsm_data"]["version"] = "0.7.0"
    manifest["packages"]["epsm_data"]["revision"] = "b" * 40
    manifest_path.write_text(json.dumps(manifest))
    assert render(repository, "--check").returncode != 0
    assert render(repository).returncode == 0
    after = (repository / "README.md").read_text()
    assert f"| `epsm_data` | 0.7.0 | `{'b' * 40}` |" in after
    assert "Historical release: Data 0.5.0 at old-release." in after
    assert render(repository, "--check").returncode == 0


def test_render_preserves_crlf_outside_the_generated_block(repository):
    readme = repository / "README.md"
    original = readme.read_bytes().replace(b"\n", b"\r\n")
    readme.write_bytes(original)
    result = render(repository)
    assert result.returncode == 0, result.stderr
    updated = readme.read_bytes()
    assert updated.split(START.encode())[0] == original.split(START.encode())[0]
    assert updated.split(END.encode())[1] == original.split(END.encode())[1]
    assert b"\n" not in updated.replace(b"\r\n", b"")


def metadata_configuration():
    yaml = pytest.importorskip(
        "yaml", reason="Metadata CI installs PyYAML from requirements-ci-metadata.txt"
    )
    workflow = yaml.safe_load((ROOT / ".github/workflows/metadata.yml").read_text())
    checkout = yaml.safe_load(
        (ROOT / ".github/actions/checkout-metadata/action.yml").read_text()
    )
    registry = json.loads((ROOT / "platform-registry.json").read_text())
    return workflow, checkout, registry


def test_metadata_checkouts_cover_active_registry_packages_at_main_only():
    workflow, checkout, registry = metadata_configuration()
    expected = {
        (package["repository"], f".ci/{name}")
        for name, package in registry["packages"].items()
        if name != "epsm" and package["status"] == "active"
    }
    steps = workflow["jobs"]["metadata"]["steps"]
    checkouts = [
        step["with"]
        for step in steps
        if step.get("uses") == "./.github/actions/checkout-metadata"
    ]
    assert len(checkouts) == len(expected), (
        "Each active collaborator needs one checkout"
    )
    assert {(step["repository"], step["path"]) for step in checkouts} == expected
    assert all("ref" not in step for step in checkouts)
    assert checkout["runs"]["using"] == "composite"
    owned_steps = checkout["runs"]["steps"]
    assert len(owned_steps) == 1
    settings = owned_steps[0]["with"]
    assert settings["ref"] == "main"
    assert settings["fetch-depth"] == 1
    assert settings["persist-credentials"] is False
    assert settings["sparse-checkout-cone-mode"] is False
    assert "/pyproject.toml" in settings["sparse-checkout"].splitlines()


def test_metadata_workflow_keeps_one_short_job_without_a_scientific_matrix():
    workflow, _, _ = metadata_configuration()
    assert set(workflow["jobs"]) == {"metadata"}
    job = workflow["jobs"]["metadata"]
    assert job["timeout-minutes"] == 5
    assert "strategy" not in job
    assert workflow["permissions"] == {"contents": "read"}
    commands = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python -m build" not in commands
    assert "check_installed_platform.py" not in commands
    assert "run_examples.py" not in commands


def test_metadata_job_runs_only_the_pure_guard_test_files():
    workflow, _, _ = metadata_configuration()
    commands = [
        shlex.split(line)
        for step in workflow["jobs"]["metadata"]["steps"]
        for line in step.get("run", "").splitlines()
        if line.strip().startswith("python -m pytest ")
    ]
    assert len(commands) == 1
    targets = [argument for argument in commands[0] if argument.startswith("tests")]
    assert len(targets) == 5
    assert set(targets) == {
        "tests/test_platform_metadata.py",
        "tests/test_ci_references.py",
        "tests/test_compatibility_matrix.py",
        "tests/test_compatibility_references.py",
        "tests/test_compatibility_receipt.py",
    }


def test_platform_gate_retains_logging_checks_without_a_second_wheel_matrix():
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    steps = workflow["jobs"]["platform"]["steps"]
    commands = "\n".join(step.get("run", "") for step in steps)
    assert "python scripts/verify_logging_installation.py" in commands
    assert any(
        step.get("env", {}).get("EPSM_LOGGING_INTEGRATION") == "1"
        and "python -m pytest" in step.get("run", "")
        for step in steps
    )
    assert "python scripts/run_examples.py --integration" in commands
    artifacts = [
        step.get("with", {}).get("path", "")
        for step in steps
        if step.get("uses", "").startswith("actions/upload-artifact@")
    ]
    assert any("build/logging-verification.json" in paths for paths in artifacts)
    assert not (ROOT / ".github/workflows/logging.yml").exists()
