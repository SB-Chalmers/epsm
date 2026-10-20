# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Check display-gate evidence and prerequisite failures without running engines."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_viewer_handoff.py"


@pytest.fixture
def handoff():
    spec = importlib.util.spec_from_file_location("viewer_handoff", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def combination(tmp_path):
    path = tmp_path / "compatibility.json"
    path.write_text(
        json.dumps(
            {
                "packages": {
                    "epsm_core": {"version": "0.8.0", "revision": "a" * 40},
                    "epsm_viewer": {
                        "version": "0.1.0",
                        "revision": "b" * 40,
                        "role": "display",
                    },
                }
            }
        )
    )
    return path


def test_requires_captured_source_revisions_matching_the_manifest(handoff, combination):
    selected = handoff.read_combination(combination, "a" * 40, "b" * 40)
    assert selected["epsm_core"]["version"] == "0.8.0"
    assert selected["epsm_viewer"]["revision"] == "b" * 40
    with pytest.raises(RuntimeError, match="checkout.*manifest"):
        handoff.read_combination(combination, "c" * 40, "b" * 40)


@pytest.mark.parametrize("revision", ["main", "self", "", "a" * 39])
def test_moving_or_missing_source_identity_is_not_release_evidence(
    handoff, combination, revision
):
    with pytest.raises(RuntimeError, match="SHA-40"):
        handoff.read_combination(combination, revision, "b" * 40)


def test_missing_display_entry_fails_before_importing_packages(handoff, combination):
    combination.write_text('{"packages": {}}')
    with pytest.raises(RuntimeError, match="epsm_core|epsm_viewer"):
        handoff.read_combination(combination, "a" * 40, "b" * 40)


def test_installed_version_must_match_manifest(handoff, monkeypatch):
    monkeypatch.setattr(handoff.metadata, "version", lambda name: "0.7.1")
    with pytest.raises(RuntimeError, match="version.*manifest"):
        handoff.installed_package(
            "epsm_core", {"version": "0.8.0", "revision": "a" * 40}
        )


def test_editable_package_is_not_an_installed_wheel_gate(handoff, monkeypatch):
    monkeypatch.setattr(handoff.metadata, "version", lambda name: "0.8.0")
    monkeypatch.setattr(
        handoff.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            __file__="/environment/site-packages/epsm_core/__init__.py"
        ),
    )
    monkeypatch.setattr(
        handoff.metadata,
        "distribution",
        lambda name: SimpleNamespace(
            read_text=lambda path: '{"dir_info":{"editable":true}}'
        ),
    )
    with pytest.raises(RuntimeError, match="Installed wheel required"):
        handoff.installed_package(
            "epsm_core", {"version": "0.8.0", "revision": "a" * 40}
        )


def test_javascript_failure_is_required_failure_without_a_fallback(
    handoff, tmp_path, monkeypatch
):
    (tmp_path / "package.json").write_text('{"name":"epsm_viewer","version":"0.1.0"}')

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1, args[0], stderr="Unsupported scene schema"
        )

    monkeypatch.setattr(handoff.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="JavaScript.*Unsupported scene schema"):
        handoff.prepare_javascript_scene({"objects": []}, tmp_path, "node", "0.1.0")


def test_javascript_cannot_claim_success_after_losing_object_identity(
    handoff, tmp_path, monkeypatch
):
    (tmp_path / "package.json").write_text('{"name":"epsm_viewer","version":"0.1.0"}')
    result = subprocess.CompletedProcess(
        [],
        0,
        json.dumps(
            {
                "schema": "epsm.scene/1",
                "units": "m",
                "up_axis": "Z",
                "object_ids": ["different"],
                "triangle_count": 2,
                "node_version": "v22.0.0",
            }
        ),
        "",
    )
    monkeypatch.setattr(handoff.subprocess, "run", lambda *args, **kwargs: result)
    scene = {
        "schema": "epsm.scene/1",
        "units": "m",
        "up_axis": "Z",
        "objects": [{"id": "wall"}],
    }
    with pytest.raises(RuntimeError, match="identit"):
        handoff.prepare_javascript_scene(scene, tmp_path, "node", "0.1.0")


def test_failed_required_check_writes_failure_receipt(handoff, tmp_path, monkeypatch):
    def fail(args):
        raise RuntimeError("Required Node prerequisite unavailable")

    monkeypatch.setattr(handoff, "run_handoff", fail)
    output = tmp_path / "evidence/viewer.json"
    status = handoff.main(
        [
            "--viewer-javascript-root",
            str(tmp_path),
            "--core-revision",
            "a" * 40,
            "--viewer-revision",
            "b" * 40,
            "--output",
            str(output),
        ]
    )
    assert status == 1
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "failed"
    assert "Node prerequisite" in receipt["error"]
