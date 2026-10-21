# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Logging evidence distinguishes tested pins from explicit main candidates."""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "logging_installation",
    Path(__file__).resolve().parents[1] / "scripts/verify_logging_installation.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_logging_cli_uses_the_selected_candidate_manifest(tmp_path, monkeypatch):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "kind": "candidate",
                "packages": {"epsm": {"version": "0.4.0", "revision": "self"}},
            }
        )
    )
    observed = {}

    def collect(root, manifest, **options):
        observed.update(manifest)
        return {"packages": manifest["packages"]}

    monkeypatch.setattr(
        MODULE, "__file__", str(tmp_path / "scripts/verify_logging_installation.py")
    )
    monkeypatch.setattr(MODULE, "collect_logging", collect)
    monkeypatch.setattr(sys, "argv", ["logging", "--manifest", str(candidate)])
    MODULE.main()
    assert observed["packages"]["epsm"]["version"] == "0.4.0"


@pytest.fixture
def cohort(monkeypatch, tmp_path):
    root = tmp_path / "epsm"
    versions = {"epsm": "0.3.1", "epsm_core": "0.8.0"}
    revisions = {root: "a" * 40, root / ".ci/epsm_core": "b" * 40}
    imported = {
        name: tmp_path / "env/lib/python3.13/site-packages" / name / "__init__.py"
        for name in versions
    }
    editable = {name: False for name in versions}
    monkeypatch.setattr(
        MODULE.subprocess,
        "check_output",
        lambda command, *, cwd, text: revisions[Path(cwd)],
    )
    monkeypatch.setattr(MODULE.metadata, "version", versions.__getitem__)
    monkeypatch.setattr(
        MODULE.importlib,
        "import_module",
        lambda name: SimpleNamespace(__file__=imported[name]),
    )
    monkeypatch.setattr(
        MODULE.metadata,
        "distribution",
        lambda name: SimpleNamespace(
            read_text=lambda filename: json.dumps(
                {"dir_info": {"editable": editable[name]}}
            )
        ),
    )
    manifest = {
        "packages": {
            "epsm": {"revision": "self", "version": "0.3.1"},
            "epsm_core": {"revision": "b" * 40, "version": "0.8.0"},
            "epsm_viewer": {
                "revision": "c" * 40,
                "version": "0.1.0",
                "role": "display",
            },
        }
    }
    return root, manifest, versions, revisions, imported, editable


def test_pinned_logging_evidence_records_actual_revisions(cohort):
    root, manifest, _, _, _, _ = cohort
    result = MODULE.collect_logging(root, manifest, mode="pinned")
    assert result["mode"] == "pinned"
    assert result["packages"]["epsm"]["revision"] == "a" * 40
    assert result["packages"]["epsm_core"]["revision"] == "b" * 40
    assert result["packages"]["epsm_core"]["editable"] is False
    assert "epsm_viewer" not in result["packages"]


@pytest.mark.parametrize("changed", ["revision", "version"])
def test_pinned_logging_rejects_changed_supported_cohort(cohort, changed):
    root, manifest, versions, revisions, _, _ = cohort
    if changed == "revision":
        revisions[root / ".ci/epsm_core"] = "d" * 40
    else:
        versions["epsm_core"] = "0.9.0"
    with pytest.raises(RuntimeError, match="Unexpected"):
        MODULE.collect_logging(root, manifest, mode="pinned")


def test_main_logging_records_candidates_without_claiming_supported_pins(cohort):
    root, manifest, versions, revisions, _, _ = cohort
    versions["epsm_core"] = "0.9.0"
    revisions[root / ".ci/epsm_core"] = "d" * 40
    result = MODULE.collect_logging(root, manifest, mode="main")
    assert result["mode"] == "main"
    assert result["packages"]["epsm_core"]["version"] == "0.9.0"
    assert result["packages"]["epsm_core"]["revision"] == "d" * 40
    assert manifest["packages"]["epsm_core"]["revision"] == "b" * 40


@pytest.mark.parametrize("mode", ["pinned", "main"])
@pytest.mark.parametrize("violation", ["source", "editable"])
def test_logging_always_requires_installed_noneditable_wheels(cohort, mode, violation):
    root, manifest, _, _, imported, editable = cohort
    if violation == "source":
        imported["epsm_core"] = root / ".ci/epsm_core/src/epsm_core/__init__.py"
    else:
        editable["epsm_core"] = True
    with pytest.raises(RuntimeError, match="installed wheel"):
        MODULE.collect_logging(root, manifest, mode=mode)


def test_logging_rejects_unknown_mode(cohort):
    root, manifest, _, _, _, _ = cohort
    with pytest.raises(ValueError, match="pinned or main"):
        MODULE.collect_logging(root, manifest, mode="candidate")
