# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Environment migration preserves old files when verification fails."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def setup_script(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/setup_shared_venv.py"
    spec = importlib.util.spec_from_file_location("setup_shared_venv", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    central = tmp_path / "epsm/.venv"
    central.mkdir(parents=True)
    monkeypatch.setattr(module, "GITHUB", tmp_path)
    monkeypatch.setattr(module, "CENTRAL", central)
    return module


def old_environment(root):
    path = root / "epsm_core/.venv"
    path.mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("example old virtual environment")
    (path / "keep.txt").write_text("original environment evidence")
    return path


def test_verified_migration_and_repeated_call_use_the_same_central_environment(
    setup_script, monkeypatch
):
    module = setup_script
    path = old_environment(module.GITHUB)
    checked = []
    monkeypatch.setattr(module, "run", lambda *args: checked.append(path.resolve()))
    module.migrate_one("epsm_core")
    assert path.is_symlink() and path.resolve() == module.CENTRAL.resolve()
    assert checked == [module.CENTRAL.resolve()]
    assert not path.with_name(".venv.epsm-migration-backup").exists()
    module.migrate_one("epsm_core")
    assert path.resolve() == module.CENTRAL.resolve()
    assert len(checked) == 1


def test_failed_link_verification_restores_the_original_environment(
    setup_script, monkeypatch
):
    module = setup_script
    path = old_environment(module.GITHUB)

    def fail(*args):
        raise RuntimeError("interpreter check failed")

    monkeypatch.setattr(module, "run", fail)
    with pytest.raises(RuntimeError, match="interpreter check failed"):
        module.migrate_one("epsm_core")
    assert path.is_dir() and not path.is_symlink()
    assert (path / "keep.txt").read_text() == "original environment evidence"
    assert not path.with_name(".venv.epsm-migration-backup").exists()


def test_migration_refuses_a_link_to_another_environment(setup_script):
    module = setup_script
    other = module.GITHUB / "another-environment"
    other.mkdir()
    checkout = module.GITHUB / "epsm_core"
    checkout.mkdir()
    path = checkout / ".venv"
    path.symlink_to(other, target_is_directory=True)
    with pytest.raises(RuntimeError, match="points elsewhere"):
        module.migrate_one("epsm_core")
    assert path.resolve() == other.resolve()
