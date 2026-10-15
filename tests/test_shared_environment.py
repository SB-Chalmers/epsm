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


def installed_checkout(
    module, tmp_path, monkeypatch, *, declared="0.2.0", installed="0.1.0"
):
    import json
    from types import SimpleNamespace

    checkout = tmp_path / "library"
    source = checkout / "src/library"
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("")
    (checkout / "pyproject.toml").write_text(
        f'[project]\nname="library"\nversion="{declared}"\n'
    )
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda _: SimpleNamespace(__file__=str(source / "__init__.py")),
    )
    monkeypatch.setattr(module.metadata, "version", lambda _: installed)
    distribution = SimpleNamespace(
        read_text=lambda _: json.dumps(
            {
                "dir_info": {"editable": True},
                "url": checkout.as_uri(),
            }
        )
    )
    monkeypatch.setattr(module.metadata, "distribution", lambda _: distribution)
    return checkout


def test_verification_rejects_stale_metadata_with_reinstall_instruction(
    setup_script, tmp_path, monkeypatch
):
    checkout = installed_checkout(setup_script, tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="library.*0.1.0.*0.2.0.*setup_shared_venv"):
        setup_script.verify_checkout("library", "library", checkout)


def test_verification_accepts_matching_feature_checkout_without_git_access(
    setup_script, tmp_path, monkeypatch
):
    checkout = installed_checkout(
        setup_script, tmp_path, monkeypatch, installed="0.2.0"
    )
    setup_script.verify_checkout("library", "library", checkout)


def test_dynamic_version_is_read_from_current_source(
    setup_script, tmp_path, monkeypatch
):
    checkout = installed_checkout(
        setup_script, tmp_path, monkeypatch, installed="0.2.0"
    )
    (checkout / "pyproject.toml").write_text(
        '[project]\nname="library"\ndynamic=["version"]\n'
        '[tool.setuptools.dynamic]\nversion={attr="library._version.__version__"}\n'
    )
    (checkout / "src/library/_version.py").write_text('__version__="0.3.0"\n')
    with pytest.raises(RuntimeError, match="0.2.0.*0.3.0"):
        setup_script.verify_checkout("library", "library", checkout)


def test_verification_rejects_an_old_rc_api(setup_script, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        setup_script.importlib,
        "import_module",
        lambda _: SimpleNamespace(RCSettings=type("OldSettings", (), {})),
    )
    with pytest.raises(RuntimeError, match="epsm_rc.*from_policy.*setup_shared_venv"):
        setup_script.verify_capabilities()
