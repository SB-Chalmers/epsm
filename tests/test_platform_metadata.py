# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""The platform guard reads committed metadata, without importing packages."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_platform_metadata.py"


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root, files):
    for name, contents in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Fixture metadata",
    )
    return git(root, "rev-parse", "HEAD")


def project(name, version="1.0.0", *, dependencies=(), extras=None, python=">=3.11"):
    text = (
        f"[project]\nname = {json.dumps(name)}\nversion = {json.dumps(version)}\n"
        f"requires-python = {json.dumps(python)}\n"
        f"dependencies = {json.dumps(list(dependencies))}\n"
    )
    if extras:
        text += "[project.optional-dependencies]\n"
        text += "".join(
            f"{key} = {json.dumps(value)}\n" for key, value in extras.items()
        )
    return text


@pytest.fixture
def platform(tmp_path):
    root, sources = tmp_path / "epsm", tmp_path / "sources"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    own_sha = commit(root, {"pyproject.toml": project("epsm")})
    core = sources / "epsm_core"
    core.mkdir(parents=True)
    git(core, "init", "-q", "-b", "main")
    core_sha = commit(core, {"pyproject.toml": project("epsm-core")})
    registry = {
        "format": 1,
        "packages": {
            name: {
                "repository": f"SB-Chalmers/{name}",
                "branch": "main",
                "extras": [],
                "status": "active",
            }
            for name in ("epsm", "epsm_core")
        },
    }
    policy = {
        "format": 1,
        "python": ["3.11", "3.13"],
        "packages": {
            "epsm": {"version": "1.0.0", "revision": "self"},
            "epsm_core": {"version": "1.0.0", "revision": core_sha},
        },
    }
    return root, sources, registry, policy, own_sha, core_sha


def check(platform, *, mode="pinned"):
    root, sources, registry, policy, *_ = platform
    (root / "platform-registry.json").write_text(json.dumps(registry))
    (root / "compatibility.json").write_text(json.dumps(policy))
    spec = importlib.util.spec_from_file_location("platform_metadata_checker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check_platform(root, sources, mode)


def codes(report):
    return {row["code"] for row in report["findings"]}


def test_pinned_reads_old_commit_and_ignores_dirty_and_newer_main(platform):
    root, sources, _, _, _, core_sha = platform
    core = sources / "epsm_core"
    commit(core, {"pyproject.toml": project("epsm_core", "2.0.0")})
    (core / "pyproject.toml").write_text("not valid TOML")
    report = check(platform)
    assert report["status"] == "passed"
    assert report["packages"]["epsm_core"]["revision"] == core_sha
    assert report["packages"]["epsm_core"]["version"] == "1.0.0"
    assert (root / "compatibility.json").read_text() == json.dumps(platform[3])


def test_main_resolves_main_instead_of_feature_head_or_dirty_work(platform):
    core = platform[1] / "epsm_core"
    sha = commit(core, {"pyproject.toml": project("epsm_core", "1.1.0")})
    git(core, "checkout", "-qb", "codex/work-in-progress")
    commit(core, {"pyproject.toml": project("epsm_core", "99.0")})
    (core / "pyproject.toml").write_text("broken dirty metadata")
    report = check(platform, mode="main")
    row = report["packages"]["epsm_core"]
    assert report["status"] == "passed"
    assert row["version"] == "1.1.0" and row["revision"] == sha
    assert row["selected_ref"] == "refs/heads/main"
    assert "candidate_drift" in codes(report)
    assert row["integration_status"] == "unverified"


def test_detached_checkout_uses_head_when_main_refs_are_absent(platform):
    core = platform[1] / "epsm_core"
    git(core, "checkout", "-q", "--detach")
    git(core, "branch", "-D", "main")
    report = check(platform, mode="main")
    assert report["status"] == "passed"
    assert report["packages"]["epsm_core"]["selected_ref"] == "HEAD"


def test_remote_main_precedes_detached_head(platform):
    core = platform[1] / "epsm_core"
    git(core, "update-ref", "refs/remotes/origin/main", platform[5])
    commit(core, {"pyproject.toml": project("epsm_core", "99.0")})
    git(core, "checkout", "-q", "--detach")
    git(core, "branch", "-D", "main")
    report = check(platform, mode="main")
    assert report["packages"]["epsm_core"]["revision"] == platform[5]
    assert report["packages"]["epsm_core"]["selected_ref"] == "refs/remotes/origin/main"


def test_umbrella_main_snapshot_does_not_read_feature_dependency_bounds(platform):
    root, _, _, _, main_sha, _ = platform
    git(root, "update-ref", "refs/remotes/origin/main", main_sha)
    git(root, "checkout", "-qb", "codex/new-platform-bounds")
    feature_sha = commit(
        root,
        {"pyproject.toml": project("epsm", "2.0.0", dependencies=["epsm_core>=99"])},
    )
    git(root, "checkout", "-q", "--detach")
    git(root, "branch", "-D", "main")
    report = check(platform, mode="main")
    assert git(root, "rev-parse", "HEAD") == feature_sha
    assert report["status"] == "passed"
    own = report["packages"]["epsm"]
    assert own["revision"] == main_sha
    assert own["version"] == "1.0.0"
    assert own["selected_ref"] == "refs/remotes/origin/main"
    assert "dependency_unsatisfied" not in codes(report)


def test_feature_branch_cannot_substitute_for_missing_main(platform):
    core = platform[1] / "epsm_core"
    git(core, "branch", "-m", "codex/only-feature")
    report = check(platform, mode="main")
    assert report["status"] == "failed" and "metadata_invalid" in codes(report)


@pytest.mark.parametrize("style", ["attr", "file"])
def test_dynamic_versions_are_read_as_data_without_executing_source(platform, style):
    core = platform[1] / "epsm_core"
    metadata = '[project]\nname="epsm_core"\ndynamic=["version"]\n'
    metadata += "[tool.setuptools.dynamic]\n"
    if style == "attr":
        metadata += 'version={attr="epsm_core._version.__version__"}\n'
        files = {
            "src/epsm_core/_version.py": 'raise AssertionError("must never execute")\n__version__ = "1.0.0"\n'
        }
    else:
        metadata += 'version={file=["VERSION"]}\n'
        files = {"VERSION": "1.0.0\n"}
    sha = commit(core, {"pyproject.toml": metadata, **files})
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    assert check(platform)["status"] == "passed"


def test_dynamic_attribute_may_name_a_package_init(platform):
    core = platform[1] / "epsm_core"
    metadata = (
        '[project]\nname="epsm_core"\ndynamic=["version"]\n'
        '[tool.setuptools.dynamic]\nversion={attr="epsm_core.__version__"}\n'
    )
    sha = commit(
        core,
        {
            "pyproject.toml": metadata,
            "src/epsm_core/__init__.py": '__version__: str = "1.0.0"\n',
        },
    )
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    assert check(platform)["status"] == "passed"


def test_dynamic_attribute_with_multiple_assignments_is_rejected(platform):
    metadata = (
        '[project]\nname="epsm_core"\ndynamic=["version"]\n'
        '[tool.setuptools.dynamic]\nversion={attr="epsm_core._version.__version__"}\n'
    )
    sha = commit(
        platform[1] / "epsm_core",
        {
            "pyproject.toml": metadata,
            "src/epsm_core/_version.py": '__version__ = "1.0.0"\n__version__ = "99.0.0"\n',
        },
    )
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    report = check(platform)
    assert report["status"] == "failed" and "metadata_invalid" in codes(report)


def test_extra_names_cannot_collide_after_normalization(platform):
    sha = commit(
        platform[1] / "epsm_core",
        {
            "pyproject.toml": project(
                "epsm_core",
                extras={"fast_lane": ["epsm>=99"], "fast-lane": []},
            )
        },
    )
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    platform[2]["packages"]["epsm_core"]["extras"] = ["fast_lane"]
    report = check(platform)
    assert report["status"] == "failed" and "metadata_invalid" in codes(report)


def test_malformed_setuptools_table_produces_a_failed_report(platform):
    metadata = (
        '[project]\nname="epsm_core"\ndynamic=["version"]\n[tool]\nsetuptools=[]\n'
    )
    sha = commit(platform[1] / "epsm_core", {"pyproject.toml": metadata})
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    report = check(platform)
    assert report["status"] == "failed" and "metadata_invalid" in codes(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "main"),
        ("revision", "self"),
        ("version", "not a version"),
    ],
)
def test_invalid_supported_policy_fails_before_reading_metadata(platform, field, value):
    platform[3]["packages"]["epsm_core"][field] = value
    report = check(platform)
    assert report["status"] == "failed" and "policy_invalid" in codes(report)
    assert not report["packages"]


def test_supported_version_must_match_committed_metadata(platform):
    platform[3]["packages"]["epsm_core"]["version"] = "1.0.1"
    report = check(platform)
    assert report["status"] == "failed" and "version_mismatch" in codes(report)


def test_package_identity_must_match_registry_name(platform):
    sha = commit(platform[1] / "epsm_core", {"pyproject.toml": project("other")})
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    report = check(platform)
    assert report["status"] == "failed" and "metadata_invalid" in codes(report)


def test_internal_requirements_use_candidate_versions_not_tested_versions(platform):
    core = platform[1] / "epsm_core"
    commit(core, {"pyproject.toml": project("epsm_core", "2.0.0")})
    commit(
        platform[0],
        {"pyproject.toml": project("epsm", dependencies=["epsm-core>=2,<3"])},
    )
    assert check(platform, mode="main")["status"] == "passed"
    commit(core, {"pyproject.toml": project("epsm_core", "3.0.0")})
    report = check(platform, mode="main")
    assert report["status"] == "failed" and "dependency_unsatisfied" in codes(report)


def test_selected_extras_and_python_markers_are_checked(platform):
    metadata = project(
        "epsm",
        dependencies=["epsm_core>=1; python_version < '3.12'"],
        extras={
            "rc": ["epsm_core>=2; python_version >= '3.13'"],
            "unused": ["epsm_core>=99"],
        },
    )
    commit(platform[0], {"pyproject.toml": metadata})
    assert check(platform, mode="main")["status"] == "passed"
    platform[2]["packages"]["epsm"]["extras"] = ["rc"]
    report = check(platform, mode="main")
    assert report["status"] == "failed"
    failure = next(
        f for f in report["findings"] if f["code"] == "dependency_unsatisfied"
    )
    assert "3.13" in failure["message"]


def test_extra_marker_uses_selected_extra_context(platform):
    commit(
        platform[0],
        {
            "pyproject.toml": project(
                "epsm",
                extras={
                    "rc": ["epsm_core>=2; extra == 'rc'"],
                },
            )
        },
    )
    platform[2]["packages"]["epsm"]["extras"] = ["rc"]
    assert "dependency_unsatisfied" in codes(check(platform, mode="main"))


def test_base_extra_marker_uses_selected_extra_context(platform):
    commit(
        platform[0],
        {
            "pyproject.toml": project(
                "epsm",
                dependencies=["epsm_core>=2; extra == 'rc'"],
                extras={"rc": []},
            )
        },
    )
    assert check(platform, mode="main")["status"] == "passed"
    platform[2]["packages"]["epsm"]["extras"] = ["rc"]
    assert "dependency_unsatisfied" in codes(check(platform, mode="main"))


def test_dependency_extras_activate_transitively_through_a_cycle(platform):
    commit(
        platform[0],
        {"pyproject.toml": project("epsm", extras={"rc": ["epsm_core>=2"]})},
    )
    commit(
        platform[1] / "epsm_core",
        {
            "pyproject.toml": project("epsm_core", dependencies=["epsm[rc]>=1"]),
        },
    )
    report = check(platform, mode="main")
    assert report["status"] == "failed" and "dependency_unsatisfied" in codes(report)
    assert report["packages"]["epsm"]["effective_extras"] == ["rc"]


def test_marker_activated_extras_do_not_leak_into_other_python_lanes(platform):
    commit(
        platform[0],
        {
            "pyproject.toml": project(
                "epsm",
                extras={
                    "rc": ["epsm_core>=2; python_version >= '3.13'"],
                },
            )
        },
    )
    commit(
        platform[1] / "epsm_core",
        {
            "pyproject.toml": project(
                "epsm_core",
                dependencies=[
                    "epsm[rc]>=1; python_version < '3.12'",
                ],
            )
        },
    )
    assert check(platform, mode="main")["status"] == "passed"


def test_missing_transitively_requested_extra_fails(platform):
    commit(
        platform[0],
        {"pyproject.toml": project("epsm", dependencies=["epsm_core[missing]>=1"])},
    )
    assert "dependency_extra_missing" in codes(check(platform, mode="main"))


def test_unknown_selected_extra_fails(platform):
    platform[2]["packages"]["epsm"]["extras"] = ["missing"]
    assert "metadata_invalid" in codes(check(platform))


def test_requires_python_is_checked_for_every_supported_lane(platform):
    commit(platform[0], {"pyproject.toml": project("epsm", python=">=3.12")})
    report = check(platform, mode="main")
    assert report["status"] == "failed" and "python_unsatisfied" in codes(report)


def test_active_unpinned_package_is_unverified_without_checkout_in_pinned_mode(
    platform,
):
    platform[2]["packages"]["epsm_workflows"] = {
        "repository": "SB-Chalmers/epsm_workflows",
        "branch": "main",
        "extras": [],
        "status": "active",
    }
    report = check(platform)
    assert report["status"] == "passed"
    assert report["packages"]["epsm_workflows"]["status"] == "unpinned"
    assert "unverified_package" in codes(report)
    assert "checkout_missing" in codes(check(platform, mode="main"))


def test_missing_supported_checkout_is_not_a_passing_skip(platform):
    missing = list(platform)
    missing[1] = platform[1] / "missing"
    report = check(missing)
    assert report["status"] == "failed" and "checkout_missing" in codes(report)


def test_unpublished_package_is_explicitly_skipped_not_marked_checked(platform):
    platform[2]["packages"]["epsm_viewer"] = {
        "repository": None,
        "branch": "main",
        "extras": [],
        "status": "unpublished",
    }
    report = check(platform)
    assert report["packages"]["epsm_viewer"]["status"] == "unpublished"
    assert "unpublished_package" in codes(report)


@pytest.mark.parametrize(
    "npm_version, file_version",
    [("1.0.0", "1.0.0"), ("1.0.1", "1.0.0"), ("1.0.0", "1.0.1")],
)
def test_display_package_versions_are_read_from_committed_sources(
    platform, npm_version, file_version
):
    viewer = platform[1] / "epsm_viewer"
    viewer.mkdir()
    git(viewer, "init", "-q", "-b", "main")
    sha = commit(
        viewer,
        {
            "pyproject.toml": project("epsm_viewer"),
            "package.json": json.dumps(
                {"name": "@epsm/viewer", "version": npm_version}
            ),
            "VERSION": file_version + "\n",
        },
    )
    platform[2]["packages"]["epsm_viewer"] = {
        "repository": "SB-Chalmers/epsm_viewer",
        "branch": "main",
        "extras": [],
        "status": "active",
        "role": "display",
    }
    platform[3]["packages"]["epsm_viewer"] = {
        "version": "1.0.0",
        "revision": sha,
        "role": "display",
    }
    report = check(platform)
    assert report["status"] == (
        "passed" if npm_version == file_version == "1.0.0" else "failed"
    )


def test_supported_role_must_match_registry_boundary(platform):
    platform[3]["packages"]["epsm_core"]["role"] = "display"
    assert "policy_invalid" in codes(check(platform))


def test_metadata_path_cannot_escape_committed_repository(platform):
    core = platform[1] / "epsm_core"
    metadata = (
        '[project]\nname="epsm_core"\ndynamic=["version"]\n'
        '[tool.setuptools.dynamic]\nversion={file=["../VERSION"]}\n'
    )
    sha = commit(core, {"pyproject.toml": metadata})
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    assert "metadata_invalid" in codes(check(platform))


@pytest.mark.parametrize(
    "contents",
    [
        '[project]\nname="epsm_core"\nversion="1.0.0"\ndynamic=["dependencies"]\n',
        '[project]\nname="epsm_core"\ndynamic=["version"]\n'
        "[tool.setuptools.dynamic]\nversion={attr=1}\n",
        "project=[]\n",
    ],
)
def test_unreadable_metadata_is_a_failed_report_not_an_exception(platform, contents):
    sha = commit(platform[1] / "epsm_core", {"pyproject.toml": contents})
    platform[3]["packages"]["epsm_core"]["revision"] = sha
    report = check(platform)
    assert report["status"] == "failed" and "metadata_invalid" in codes(report)


def test_unregistered_epsm_dependency_cannot_pass_as_external(platform):
    commit(
        platform[0],
        {"pyproject.toml": project("epsm", dependencies=["epsm_missing>=1"])},
    )
    report = check(platform, mode="main")
    assert report["status"] == "failed" and "dependency_unregistered" in codes(report)


def test_cli_retains_failed_report_and_deterministic_summary(platform, tmp_path):
    platform[3]["packages"]["epsm_core"]["version"] = "1.0.1"
    # Write policy files using the same fixture helper before exercising the CLI.
    check(platform)
    output, summary = tmp_path / "report.json", tmp_path / "summary.md"
    command = [
        sys.executable,
        str(SCRIPT),
        "--root",
        str(platform[0]),
        "--sources",
        str(platform[1]),
        "--mode",
        "pinned",
        "--output",
        str(output),
        "--summary",
        str(summary),
    ]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 1, first.stderr
    assert json.loads(output.read_text())["status"] == "failed"
    original = output.read_bytes(), summary.read_bytes()
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode == 1
    assert (output.read_bytes(), summary.read_bytes()) == original
    assert "integration" in summary.read_text().lower()
