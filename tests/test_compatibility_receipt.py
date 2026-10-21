# SPDX-License-Identifier: MIT
"""Release receipts identify the installed scientific cohort and built artifacts."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "compatibility_receipt",
    Path(__file__).resolve().parents[1] / "scripts/record_compatibility.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_cli_receipt_uses_the_explicit_candidate_without_replacing_supported_pins(
    tmp_path, monkeypatch
):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(
        json.dumps(
            {
                "kind": "candidate",
                "packages": {"epsm": {"version": "0.4.0", "revision": "self"}},
            }
        )
    )
    output = tmp_path / "receipt.json"
    observed = {}

    def collect(root, manifest, **options):
        observed.update(manifest)
        return {"packages": manifest["packages"]}

    monkeypatch.setattr(MODULE, "collect_receipt", collect)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "receipt",
            "--mode",
            "pinned",
            "--manifest",
            str(candidate),
            "--output",
            str(output),
        ],
    )
    MODULE.main()
    result = json.loads(output.read_text())
    assert observed["packages"]["epsm"]["version"] == "0.4.0"
    assert result["cohort"] == "candidate" and len(result["manifest_sha256"]) == 64


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


def test_receipt_records_actual_executable_contents(tmp_path, monkeypatch):
    root = tmp_path / "epsm"
    repository(root)
    monkeypatch.setattr(MODULE.importlib.metadata, "version", lambda name: "0.3.1")
    real_run = MODULE.subprocess.run

    def run(command, **kwargs):
        if command[-1] == "--version":
            return type("Process", (), {"stdout": "EnergyPlus 24.2.0"})()
        return real_run(command, **kwargs)

    monkeypatch.setattr(MODULE.subprocess, "run", run)
    executable = tmp_path / "energyplus"
    executable.write_bytes(b"runtime-one")
    manifest = {"packages": {"epsm": {"version": "0.3.1", "revision": "self"}}}
    first = MODULE.collect_receipt(
        root, manifest, mode="pinned", energyplus_exe=executable
    )
    executable.write_bytes(b"runtime-two")
    second = MODULE.collect_receipt(
        root, manifest, mode="pinned", energyplus_exe=executable
    )
    assert first["energyplus"]["version"] == "EnergyPlus 24.2.0"
    assert first["energyplus"]["sha256"] != second["energyplus"]["sha256"]
