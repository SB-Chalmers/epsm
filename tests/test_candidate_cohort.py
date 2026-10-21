# SPDX-License-Identifier: MIT
"""Candidate checks retain exact sources and never certify a partial run."""

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("candidate_cohort", SCRIPTS / "candidate_cohort.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(path, *arguments):
    return subprocess.check_output(["git", "-C", str(path), *arguments], text=True).strip()


def source(tmp_path, *, dynamic=False):
    root = tmp_path / "demo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    version = 'dynamic = ["version"]' if dynamic else 'version = "1.2.0"'
    text = f'[project]\nname = "demo"\n{version}\nrequires-python = ">=3.11"\n'
    text += '[project.optional-dependencies]\nexample = []\n'
    if dynamic:
        text += '[tool.setuptools.dynamic]\nversion = {attr = "demo._version.__version__"}\n'
        (root / "src/demo").mkdir(parents=True)
        (root / "src/demo/_version.py").write_text('__version__ = "1.2.0"\n')
    (root / "pyproject.toml").write_text(text)
    git(root, "add", ".")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "fixture")
    return root


def registry():
    return {"packages": {"demo": {"status": "active", "extras": ["example"]}}}


@pytest.mark.parametrize("dynamic", [False, True])
def test_capture_records_committed_sources_without_importing_them(tmp_path, dynamic):
    root = source(tmp_path, dynamic=dynamic)
    result = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    assert result["kind"] == "candidate"
    assert result["packages"]["demo"] == {
        "source": str(root.resolve()), "revision": git(root, "rev-parse", "HEAD"),
        "version": "1.2.0", "extras": ["example"],
    }
    assert "self" not in json.dumps(result)


@pytest.mark.parametrize("untracked", [False, True])
def test_capture_rejects_uncommitted_inputs(tmp_path, untracked):
    root = source(tmp_path)
    (root / ("new.py" if untracked else "pyproject.toml")).write_text("changed")
    with pytest.raises(ValueError, match="uncommitted"):
        MODULE.capture_cohort(tmp_path, ["demo"], registry())


def test_capture_checks_requested_names_and_extras(tmp_path):
    source(tmp_path)
    with pytest.raises(ValueError, match="Unknown"):
        MODULE.capture_cohort(tmp_path, ["missing"], registry())
    policy = registry()
    policy["packages"]["demo"]["extras"] = ["nonexistent"]
    with pytest.raises(ValueError, match="extra"):
        MODULE.capture_cohort(tmp_path, ["demo"], policy)


def test_revalidation_rejects_source_moved_after_capture(tmp_path):
    root = source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    (root / "another").write_text("next revision")
    git(root, "add", "another")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "commit", "-qm", "second")
    with pytest.raises(ValueError, match="revision"):
        MODULE.validate_cohort(manifest)


@pytest.mark.parametrize("replacement", ["dev", "self", "a" * 39, None])
def test_moving_or_incomplete_revisions_are_rejected(tmp_path, replacement):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    manifest["packages"]["demo"]["revision"] = replacement
    with pytest.raises(ValueError, match="revision"):
        MODULE.validate_cohort(manifest)


def test_wheel_identity_uses_packaged_metadata_and_actual_bytes(tmp_path):
    wheel = tmp_path / "demo-1.2.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as stream:
        stream.writestr("demo-1.2.0.dist-info/METADATA", "Name: demo\nVersion: 1.2.0\n")
    first = MODULE.wheel_identity(wheel, "demo", "1.2.0")
    assert len(first["sha256"]) == 64
    assert first["version"] == "1.2.0"
    with pytest.raises(ValueError, match="version"):
        MODULE.wheel_identity(wheel, "demo", "1.3.0")
    with pytest.raises(ValueError, match="name"):
        MODULE.wheel_identity(wheel, "different", "1.2.0")


def test_candidate_subprocess_environment_cannot_import_editable_siblings(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/unreviewed/source")
    monkeypatch.setenv("PYTHONHOME", "/unreviewed/runtime")
    monkeypatch.setenv("VIRTUAL_ENV", "/old/venv")
    monkeypatch.setenv("EXPLICIT_ENGINE_PATH", "/declared/engine")
    result = MODULE.clean_environment()
    assert not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"} & result.keys()
    assert result["EXPLICIT_ENGINE_PATH"] == "/declared/engine"


def test_failed_build_keeps_failure_receipt_and_unrun_required_scenarios(tmp_path, monkeypatch):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    destination = tmp_path / "verification"

    def fail(*args, **kwargs):
        raise RuntimeError("build prerequisite absent")

    monkeypatch.setattr(MODULE, "execute", fail)
    with pytest.raises(RuntimeError, match="prerequisite"):
        MODULE.verify_cohort(manifest, destination, python=sys.executable,
                             scenarios=["installed-platform"])
    receipt = json.loads((destination / "receipt.json").read_text())
    assert receipt["status"] == "failed"
    assert receipt["scenarios"]["installed-platform"]["status"] == "not_run"
    assert "build prerequisite absent" in receipt["error"]
    assert receipt["packages"] == manifest["packages"]


def test_output_reuse_and_unknown_scenarios_fail_before_building(tmp_path):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    with pytest.raises(ValueError, match="Unknown scenario"):
        MODULE.verify_cohort(manifest, tmp_path / "unknown", scenarios=["misspelled"])
    output = tmp_path / "old"
    output.mkdir()
    (output / "receipt.json").write_text("preserve me")
    with pytest.raises(FileExistsError):
        MODULE.verify_cohort(manifest, output)
    assert (output / "receipt.json").read_text() == "preserve me"


def test_archive_uses_committed_files_and_never_the_mutable_checkout(tmp_path):
    root = source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    (root / "pyproject.toml").write_text("changed after capture")
    destination = tmp_path / "snapshot"
    MODULE._archive(manifest["packages"]["demo"], destination)
    assert 'version = "1.2.0"' in (destination / "pyproject.toml").read_text()
    assert not (destination / ".git").exists()


def test_successful_receipt_only_claims_selected_checks(tmp_path, monkeypatch):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())

    def simulate(command, *, directory, log):
        Path(log).write_text("")
        if "wheel" in command:
            wheel = directory / "wheels/demo-1.2.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as stream:
                stream.writestr("demo-1.2.0.dist-info/METADATA", "Name: demo\nVersion: 1.2.0\n")
        if "-c" in command:
            Path(log).write_text(json.dumps({"python": "fixture", "packages": {
                "demo": {"version": "1.2.0", "import_path": "fixture/site-packages/demo.py"},
            }}))

    monkeypatch.setattr(MODULE, "execute", simulate)
    result = MODULE.verify_cohort(manifest, tmp_path / "checked")
    assert result["status"] == "passed"
    assert result["scenarios"] == {}
    assert result["installed"]["packages"]["demo"]["version"] == "1.2.0"
    assert all(stage["status"] == "passed" for stage in result["stages"])
    assert result["wheels"]["demo"]["filename"] == "demo-1.2.0-py3-none-any.whl"


def test_missing_required_scenario_is_a_failed_gate(tmp_path, monkeypatch):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())

    def simulate(command, *, directory, log):
        Path(log).write_text("{}")
        if "wheel" in command:
            wheel = directory / "wheels/demo-1.2.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as stream:
                stream.writestr("demo-1.2.0.dist-info/METADATA", "Name: demo\nVersion: 1.2.0\n")

    monkeypatch.setattr(MODULE, "execute", simulate)
    destination = tmp_path / "checked"
    with pytest.raises(ValueError, match="Required scenario"):
        MODULE.verify_cohort(manifest, destination, scenarios=["study-platform"])
    result = json.loads((destination / "receipt.json").read_text())
    assert result["status"] == "failed"
    assert result["scenarios"]["study-platform"]["status"] == "failed"


@pytest.mark.parametrize("changes", [
    {"format": True}, {"format": 2}, {"kind": "supported"}, {"packages": {}},
])
def test_candidate_and_supported_records_cannot_be_confused(tmp_path, changes):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    manifest.update(changes)
    with pytest.raises(ValueError, match="candidate"):
        MODULE.validate_cohort(manifest)


@pytest.mark.parametrize("field,value,match", [
    ("source", "relative/path", "absolute"),
    ("version", "9.0.0", "version"),
    ("extras", ["missing"], "extras"),
    ("extras", ["example", "example"], "extras"),
])
def test_modified_manifest_fields_fail_before_build(tmp_path, field, value, match):
    source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    manifest["packages"]["demo"][field] = value
    with pytest.raises(ValueError, match=match):
        MODULE.validate_cohort(manifest)


def test_revalidation_rejects_dirty_source(tmp_path):
    root = source(tmp_path)
    manifest = MODULE.capture_cohort(tmp_path, ["demo"], registry())
    (root / "untracked").write_text("uncommitted")
    with pytest.raises(ValueError, match="uncommitted"):
        MODULE.validate_cohort(manifest)


def test_subprocess_failure_retains_real_output(tmp_path):
    log = tmp_path / "failed.log"
    with pytest.raises(RuntimeError, match="failed \\(7\\)"):
        MODULE.execute([sys.executable, "-I", "-c", "print('retained failure'); exit(7)"],
                       directory=tmp_path, log=log)
    assert "retained failure" in log.read_text()


def test_cli_capture_is_repeatable_and_refuses_overwrite(tmp_path):
    source(tmp_path)
    policy = tmp_path / "registry.json"
    policy.write_text(json.dumps(registry()))
    output = tmp_path / "candidate.json"
    arguments = ["capture", "--sources", str(tmp_path), "--registry", str(policy),
                 "--output", str(output)]
    assert MODULE.main(arguments) == 0
    content = output.read_text()
    assert json.loads(content)["packages"]["demo"]["version"] == "1.2.0"
    with pytest.raises(SystemExit) as error:
        MODULE.main(arguments)
    assert error.value.code == 1
    assert output.read_text() == content


def test_cli_verify_passes_declared_prerequisites_to_the_harness(tmp_path, monkeypatch):
    source(tmp_path)
    manifest = tmp_path / "candidate.json"
    manifest.write_text(json.dumps(MODULE.capture_cohort(tmp_path, ["demo"], registry())))
    observed = {}

    def verify(candidate, directory, **kwargs):
        observed.update(kwargs)
        observed["candidate"] = candidate

    monkeypatch.setattr(MODULE, "verify_cohort", verify)
    assert MODULE.main(["verify", "--manifest", str(manifest), "--directory", str(tmp_path / "verify"),
                        "--scenario", "study-platform", "--requirements", str(tmp_path / "requirements.txt"),
                        "--dependency-wheels", str(tmp_path / "third-party"), "--no-index"]) == 0
    assert observed["no_index"] is True
    assert observed["scenarios"] == ["study-platform"]
    assert observed["requirements"] == tmp_path / "requirements.txt"
