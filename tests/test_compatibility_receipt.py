# SPDX-License-Identifier: MIT
"""Release receipts identify the installed scientific cohort and built artifacts."""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "compatibility_receipt",
    Path(__file__).resolve().parents[1] / "scripts/record_compatibility.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def repository(path):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    (path / "example").write_text("fixture")
    subprocess.run(["git", "-C", str(path), "add", "example"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    return subprocess.check_output(
        ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
    ).strip()


def test_display_is_not_an_installed_worker_requirement(tmp_path, monkeypatch):
    root = tmp_path / "epsm"
    sha = repository(root)
    manifest = {
        "packages": {
            "epsm": {"version": "0.3.1", "revision": "self"},
            "epsm_viewer": {
                "version": "0.1.0",
                "revision": "a" * 40,
                "role": "display",
            },
        }
    }
    monkeypatch.setattr(
        MODULE.importlib.metadata, "version", lambda name: {"epsm": "0.3.1"}[name]
    )
    result = MODULE.collect_receipt(root, manifest, mode="pinned")
    assert result["manifest_revision"] == sha
    assert result["packages"] == {"epsm": {"revision": sha, "version": "0.3.1"}}
    assert "epsm_viewer" not in json.dumps(result)


def test_receipt_rejects_a_wrong_installed_version(tmp_path, monkeypatch):
    root = tmp_path / "epsm"
    repository(root)
    monkeypatch.setattr(MODULE.importlib.metadata, "version", lambda name: "0.3.0")
    with pytest.raises(RuntimeError, match="installed"):
        MODULE.collect_receipt(
            root,
            {"packages": {"epsm": {"version": "0.3.1", "revision": "self"}}},
            mode="pinned",
        )


def test_receipt_hashes_the_actual_wheel_files(tmp_path, monkeypatch):
    root = tmp_path / "epsm"
    repository(root)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "epsm-0.3.1-py3-none-any.whl"
    wheel.write_bytes(b"first artifact")
    monkeypatch.setattr(MODULE.importlib.metadata, "version", lambda name: "0.3.1")
    manifest = {"packages": {"epsm": {"version": "0.3.1", "revision": "self"}}}
    first = MODULE.collect_receipt(root, manifest, mode="pinned", wheels=wheels)
    wheel.write_bytes(b"changed artifact")
    second = MODULE.collect_receipt(root, manifest, mode="pinned", wheels=wheels)
    assert first["wheels"][wheel.name] != second["wheels"][wheel.name]
