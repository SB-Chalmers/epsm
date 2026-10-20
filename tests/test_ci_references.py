# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
"""CI reference audits use captured commits and preserve intentional baselines."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/audit_ci_references.py"
CORE_REFERENCE = "3e0256d70c5e82849308b05544b1ad2fd0573665"
RC_REFERENCE = "5a9d5f4251847e270b5dc4a526a4b2260915a4f9"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Captured workflow",
    )
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def platform(tmp_path):
    root, sources = tmp_path / "epsm", tmp_path / "sources"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    metadata = {"packages": {}, "status": "passed"}
    registry = {"format": 1, "packages": {}}
    for name in ("epsm", "epsm_core", "epsm_rc"):
        source = root if name == "epsm" else sources / name
        if name != "epsm":
            source.mkdir(parents=True)
            git(source, "init", "-q", "-b", "main")
        sha = commit(
            source, {"pyproject.toml": f'[project]\nname="{name}"\nversion="1.0.0"\n'}
        )
        metadata["packages"][name] = {"revision": sha, "version": "1.0.0"}
        registry["packages"][name] = {
            "repository": f"SB-Chalmers/{name}",
            "status": "active",
        }
    policy = {"packages": {"epsm_core": {"revision": "f" * 40, "version": "0.9.0"}}}
    return root, sources, registry, policy, metadata


def workflow(platform, text, package="epsm"):
    root, sources, _, _, metadata = platform
    source = root if package == "epsm" else sources / package
    sha = commit(source, {".github/workflows/tests.yml": text})
    metadata["packages"][package]["revision"] = sha
    return sha


def audit(platform):
    root, sources, registry, policy, metadata = platform
    (root / "platform-registry.json").write_text(json.dumps(registry))
    (root / "compatibility.json").write_text(json.dumps(policy))
    spec = importlib.util.spec_from_file_location("ci_reference_auditor", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit_references(root, sources, metadata)


def test_literal_refs_are_current_supported_or_warning_and_dynamic_is_unverified(
    platform,
):
    current = platform[4]["packages"]["epsm_core"]["revision"]
    workflow(
        platform,
        f"""jobs:
  check:
    steps:
      - uses: actions/checkout@v4
        with: {{repository: SB-Chalmers/epsm_core, ref: {current}}}
      - uses: actions/checkout@v4
        with: {{repository: SB-Chalmers/epsm_core, ref: {"f" * 40}}}
      - uses: actions/checkout@v4
        with: {{repository: SB-Chalmers/epsm_core, ref: {"e" * 40}}}
      - uses: actions/checkout@v4
        with:
          repository: SB-Chalmers/epsm_core
          ref: ${{{{ inputs.core_ref }}}}
      - uses: actions/checkout@v4
        with: {{repository: SB-Chalmers/outside_scope, ref: {"e" * 40}}}
""",
    )
    result = audit(platform)
    assert result["status"] == "passed"
    assert [row["classification"] for row in result["references"]] == [
        "current_main",
        "supported_pin",
        "outside_baseline",
        "unverified",
    ]
    assert result["references"][2]["severity"] == "warning"
    assert result["references"][3]["severity"] == "info"
    assert result["runtime_validation"] == "not_run"


def test_reads_workflow_at_captured_revision_ignoring_dirty_and_newer_work(platform):
    text = "jobs:\n  check:\n    steps:\n      - run: pip install epsm-1.0.0-py3-none-any.whl\n"
    captured = workflow(platform, text)
    root = platform[0]
    commit(root, {".github/workflows/tests.yml": text.replace("1.0.0", "99.0.0")})
    (root / ".github/workflows/tests.yml").write_text("broken: [")
    assert platform[4]["packages"]["epsm"]["revision"] == captured
    assert audit(platform)["status"] == "passed"


def test_current_own_wheel_version_mismatch_is_an_error(platform):
    workflow(
        platform,
        "jobs:\n  check:\n    steps:\n      - run: pip install epsm-0.9.0-py3-none-any.whl\n",
    )
    result = audit(platform)
    assert result["status"] == "failed"
    assert any(row["code"] == "wheel_version_mismatch" for row in result["findings"])


def test_other_package_wheel_and_historical_text_are_not_own_version_checks(platform):
    workflow(
        platform,
        "jobs:\n  check:\n    steps:\n      - run: pip install epsm_core-0.1.0-py3-none-any.whl\n",
    )
    (platform[0] / "README.md").write_text("Old wheel epsm-0.1.0-py3-none-any.whl")
    assert audit(platform)["status"] == "passed"


def test_exact_rc_numerical_baselines_are_explained_exceptions(platform):
    platform[2]["ci_reference_exceptions"] = [
        {
            "package": "epsm_rc",
            "workflow": ".github/workflows/tests.yml",
            "path": path,
            "revision": revision,
            "reason": "Independent numerical comparison baseline",
        }
        for path, revision in (
            (".ci/core_reference", CORE_REFERENCE),
            (".ci/rc_reference", RC_REFERENCE),
        )
    ]
    workflow(
        platform,
        f"""jobs:
  check:
    steps:
      - uses: actions/checkout@v4
        with: {{repository: SB-Chalmers/epsm_core, path: .ci/core_reference, ref: {CORE_REFERENCE}}}
      - uses: actions/checkout@v4
        with: {{path: .ci/rc_reference, ref: {RC_REFERENCE}}}
""",
        package="epsm_rc",
    )
    result = audit(platform)
    assert result["status"] == "passed"
    assert [row["classification"] for row in result["references"]] == [
        "intentional_baseline"
    ] * 2
    assert all(row["reason"] for row in result["references"])
    platform[2]["ci_reference_exceptions"][0]["path"] = ".ci/other_path"
    assert audit(platform)["references"][0]["classification"] == "outside_baseline"


@pytest.mark.parametrize("bad", ["missing", "unavailable", "malformed_workflow"])
def test_missing_captured_revision_and_malformed_workflows_fail(platform, bad):
    if bad == "missing":
        del platform[4]["packages"]["epsm_core"]["revision"]
    elif bad == "unavailable":
        platform[4]["packages"]["epsm_core"]["revision"] = "a" * 40
    else:
        workflow(platform, "jobs: [")
    assert audit(platform)["status"] == "failed"


@pytest.mark.parametrize("bad", ["policy_row", "observed_row", "observed_status"])
def test_malformed_reference_inputs_fail_instead_of_passing_or_crashing(platform, bad):
    if bad == "policy_row":
        platform[3]["packages"]["epsm_core"] = []
    elif bad == "observed_row":
        platform[4]["packages"]["epsm_core"] = []
    else:
        platform[4]["packages"]["epsm_core"]["status"] = False
    workflow(
        platform,
        f"""jobs:
  check:
    steps:
      - uses: actions/checkout@v4
        with: {{repository: SB-Chalmers/epsm_core, ref: {"f" * 40}}}
""",
    )
    assert audit(platform)["status"] == "failed"


def test_cli_writes_json_and_appends_an_honest_summary(platform, tmp_path):
    audit(platform)
    root, sources, _, _, metadata = platform
    metadata_path, output, summary = (
        tmp_path / name for name in ("metadata.json", "audit.json", "summary.md")
    )
    metadata_path.write_text(json.dumps(metadata))
    summary.write_text("Earlier result\n")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(root),
            "--sources",
            str(sources),
            "--metadata",
            str(metadata_path),
            "--output",
            str(output),
            "--summary",
            str(summary),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())["status"] == "passed"
    assert summary.read_text().startswith("Earlier result\n")
    assert "not run" in summary.read_text()


@pytest.mark.parametrize("explicit_sources", [False, True])
def test_cli_defaults_root_to_script_repository_and_sources_to_ci(
    platform, tmp_path, explicit_sources
):
    audit(platform)
    root, sources, _, _, metadata = platform
    installed_script = root / "scripts/audit_ci_references.py"
    installed_script.parent.mkdir()
    shutil.copyfile(SCRIPT, installed_script)
    if not explicit_sources:
        shutil.copytree(sources, root / ".ci")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata))
    arguments = [
        sys.executable,
        str(installed_script),
        "--metadata",
        str(metadata_path),
    ]
    if explicit_sources:
        arguments.extend(["--sources", str(sources)])
    result = subprocess.run(arguments, cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "passed"
