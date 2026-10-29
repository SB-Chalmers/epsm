# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Install local EPSM packages and migrate sibling .venv paths to one environment."""

from __future__ import annotations

import argparse
import ast
import importlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.parse
import venv
from importlib import metadata
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
    "epsm_db": "epsm_db",
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
    shown = (
        (*args[:2], "<inline verification>", *args[4:])
        if len(args) > 3 and args[1] == "-c"
        else args
    )
    print("+", " ".join(shown), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def checkout_version(checkout: Path) -> str:
    """Read literal static or setuptools attribute versions without cached imports."""
    project = tomllib.loads((checkout / "pyproject.toml").read_text())
    if "version" in project["project"]:
        return project["project"]["version"]
    attribute = project["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    module, name = attribute.rsplit(".", 1)
    source = checkout / "src" / (module.replace(".", "/") + ".py")
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return str(ast.literal_eval(node.value))
    raise RuntimeError(f"Cannot read declared version from {source}")


def verify_checkout(distribution: str, module: str, checkout: Path) -> None:
    """Reject stale metadata or imports from an unrelated editable checkout."""
    repair = "Run python3.12 scripts/setup_shared_venv.py from the epsm checkout."
    loaded = importlib.import_module(module)
    declared, installed = checkout_version(checkout), metadata.version(distribution)
    if installed != declared:
        raise RuntimeError(
            f"{distribution}: installed {installed}, checkout declares {declared}. {repair}"
        )
    direct = json.loads(
        metadata.distribution(distribution).read_text("direct_url.json")
    )
    actual = Path(urllib.parse.unquote(urllib.parse.urlparse(direct["url"]).path))
    if (
        not direct.get("dir_info", {}).get("editable")
        or actual.resolve() != checkout.resolve()
    ):
        raise RuntimeError(f"{distribution}: wrong editable source {actual}. {repair}")
    if not Path(loaded.__file__).resolve().is_relative_to(checkout.resolve()):
        raise RuntimeError(f"{distribution}: imported from {loaded.__file__}. {repair}")


def verify_capabilities() -> None:
    """Check public handoffs without running an engine, reading weather or using Git."""
    requirements = {
        "epsm_rc": ("RCSettings.from_policy", "simulate_building"),
        "epsm_core": ("Building.resolve", "resolve_internal_gains"),
        "epsm_lca": ("AnnualEnergy.for_building", "assess_renovation"),
    }
    for package, attributes in requirements.items():
        module = importlib.import_module(package)
        for attribute in attributes:
            value = module
            for part in attribute.split("."):
                value = getattr(value, part, None)
            if not callable(value):
                raise RuntimeError(
                    f"{package}: missing required {attribute}. Update the checkout and run "
                    "python3.12 scripts/setup_shared_venv.py from epsm."
                )


def verify() -> None:
    """Check interpreter, current source metadata, public APIs and dependencies."""
    checker = r"""
import importlib
import json
import pathlib
import sys
import urllib.parse

expected = json.loads(sys.argv[1])
assert sys.version_info[:2] == (3, 12), sys.version
assert pathlib.Path(sys.prefix).resolve() == pathlib.Path(sys.argv[2]).resolve()
spec = importlib.util.spec_from_file_location('shared_setup', sys.argv[3])
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
for distribution, (module, checkout) in expected.items():
    setup.verify_checkout(distribution, module, pathlib.Path(checkout))
setup.verify_capabilities()
importlib.import_module('pytest')
importlib.import_module('sphinx')
"""
    expected = {
        name: (module, str(GITHUB / name)) for name, module in PACKAGE_IMPORTS.items()
    }
    run(
        str(CENTRAL / "bin/python"),
        "-c",
        checker,
        json.dumps(expected),
        str(CENTRAL),
        str(Path(__file__).resolve()),
    )
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
        raise RuntimeError(
            f"Refusing to replace a path that is not a virtual environment: {path}"
        )

    if had_old:
        path.rename(backup)
    try:
        path.symlink_to(
            Path(os.path.relpath(CENTRAL, checkout)), target_is_directory=True
        )
        if path.resolve() != CENTRAL.resolve():
            raise RuntimeError(f"Link verification failed: {path}")
        run(
            str(path / "bin/python"),
            "-c",
            "import sys; assert sys.version_info[:2] == (3, 12)",
        )
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
    parser.add_argument(
        "--verify-only", action="store_true", help="Check an existing setup"
    )
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
        run(
            str(CENTRAL / "bin/python"),
            "-m",
            "pip",
            "install",
            "-r",
            "requirements-local.txt",
        )
    verify()
    if not args.verify_only:
        for name in MIGRATE:
            migrate_one(name)
        verify()
    print("Shared EPSM environment verified.", flush=True)


if __name__ == "__main__":
    main()
