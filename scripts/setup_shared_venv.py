"""Install local EPSM packages and migrate sibling .venv paths to one environment."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GITHUB = ROOT.parent
CENTRAL = ROOT / ".venv"
PACKAGE_IMPORTS = {
    "epsm": "epsm",
    "epsm_data": "epsm_data",
    "epsm_core": "epsm_core",
    "epsm_lca": "epsm_lca",
    "epsm_rc": "epsm_rc",
    "epsm_db": "sweden_ubem",
    "epsm_workflows": "epsm_workflows",
    "epsm_studies": "epsm_studies",
    "smhi2epw": "smhi2epw",
}
MIGRATE = (
    "epsm_data",  # Check this first because it may require separate write access.
    "epsm_core",
    "epsm_db",
    "epsm_development",
    "epsm_rc",
    "smhi2epw",
    "epsm_lca",
    "epsm_studies",
    "epsm_workflows",
)


def run(*args: str, cwd: Path = ROOT) -> None:
    shown = (*args[:2], "<inline verification>", *args[4:]) if len(args) > 3 and args[1] == "-c" else args
    print("+", " ".join(shown), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def verify() -> None:
    """Check interpreter, imports, editable sources, and resolved dependencies."""
    checker = r"""
import importlib
import json
import pathlib
import sys
import urllib.parse
from importlib import metadata

expected = json.loads(sys.argv[1])
assert sys.version_info[:2] == (3, 12), sys.version
assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[2]).resolve()
for distribution, (module, checkout) in expected.items():
    importlib.import_module(module)
    direct_url = json.loads(metadata.distribution(distribution).read_text('direct_url.json'))
    actual = pathlib.Path(urllib.parse.unquote(urllib.parse.urlparse(direct_url['url']).path))
    assert direct_url.get('dir_info', {}).get('editable') is True, distribution
    assert actual.resolve() == pathlib.Path(checkout).resolve(), (distribution, actual)
importlib.import_module('pytest')
importlib.import_module('sphinx')
"""
    expected = {
        name: (module, str(GITHUB / name))
        for name, module in PACKAGE_IMPORTS.items()
    }
    run(str(CENTRAL / "bin/python"), "-c", checker, json.dumps(expected), str(CENTRAL))
    run(str(CENTRAL / "bin/python"), "-m", "pip", "check")


def migrate_one(name: str) -> None:
    checkout = GITHUB / name
    path = checkout / ".venv"
    backup = checkout / ".venv.epsm-migration-backup"
    if not checkout.is_dir():
        raise RuntimeError(f"Missing checkout: {checkout}")
    if backup.exists() or backup.is_symlink():
        raise RuntimeError(f"Unresolved migration backup: {backup}")
    if path.is_symlink():
        if path.resolve() != CENTRAL.resolve():
            raise RuntimeError(f"Existing .venv link points elsewhere: {path}")
        print(f"Already linked: {path}", flush=True)
        return
    had_old = path.exists()
    if had_old and (not path.is_dir() or not (path / "pyvenv.cfg").is_file()):
        raise RuntimeError(f"Refusing to replace a path that is not a virtual environment: {path}")

    if had_old:
        path.rename(backup)
    try:
        path.symlink_to(Path(os.path.relpath(CENTRAL, checkout)), target_is_directory=True)
        if path.resolve() != CENTRAL.resolve():
            raise RuntimeError(f"Link verification failed: {path}")
        run(str(path / "bin/python"), "-c", "import sys; assert sys.version_info[:2] == (3, 12)")
    except Exception:
        if path.is_symlink():
            path.unlink()
        if had_old:
            backup.rename(path)
        raise
    if had_old:
        shutil.rmtree(backup)
        print(f"Removed old environment: {backup}", flush=True)
    print(f"Linked: {path} -> {os.readlink(path)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Check an existing setup")
    args = parser.parse_args()
    if sys.version_info[:2] != (3, 12):
        parser.error("run this script with Python 3.12")
    for name in (*PACKAGE_IMPORTS, "epsm_development"):
        if not (GITHUB / name).is_dir():
            parser.error(f"missing sibling checkout: {GITHUB / name}")
    if CENTRAL.is_symlink():
        parser.error(f"central environment must be a directory: {CENTRAL}")
    if not args.verify_only:
        if not CENTRAL.exists():
            print(f"Creating {CENTRAL}", flush=True)
            venv.EnvBuilder(with_pip=True).create(CENTRAL)
        elif not (CENTRAL / "pyvenv.cfg").is_file():
            parser.error(f"central path is not a virtual environment: {CENTRAL}")
        run(str(CENTRAL / "bin/python"), "-m", "pip", "install", "-r", "requirements-local.txt")
    verify()
    if not args.verify_only:
        for name in MIGRATE:
            migrate_one(name)
        verify()
    print("Shared EPSM environment verified.", flush=True)


if __name__ == "__main__":
    main()
