# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Capture clean candidate sources and verify their wheels in an isolated process.

This is a companion to the existing supported-manifest tools. It never changes
``compatibility.json`` or a Git branch. Candidate builds use archived committed
files rather than mutable working directories. A receipt describes only the
selected checks; an import check alone does not establish engine compatibility.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from email.parser import Parser
from pathlib import Path

from check_platform_metadata import _git, _load_json, _metadata
from packaging.utils import canonicalize_name

SCENARIOS = {
    "installed-platform": "scripts/check_installed_platform.py",
    "study-platform": "scripts/check_study_platform.py",
    "archetype-handoff": "scripts/check_archetype_handoff.py",
    "workflow-handoff": "scripts/check_workflow_handoff.py",
}


def scenario_command(name, worker, source, directory, candidate, wheels):
    """Call an existing installed scientific gate with its immutable evidence."""
    command = [
        worker,
        "-I",
        source / SCENARIOS[name],
        "--directory",
        directory,
        "--require-wheels",
    ]
    if name != "installed-platform":
        command.extend(["--compatibility-receipt", candidate, "--wheels", wheels])
    return command


def clean_environment():
    """Preserve declared engine/service settings while removing Python injection."""
    environment = dict(os.environ)
    for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    return environment


def capture_cohort(sources, packages, registry, *, extras=None):
    """Read clean HEADs and committed package metadata without importing owners.

    ``sources`` contains one checkout named after each selected package. Registry
    extras use the same ownership policy as routine compatibility checks. No
    source file, repository reference or supported release pin is modified.
    """
    if not packages or len(set(packages)) != len(packages):
        raise ValueError("Select a nonempty list of unique packages")
    additions = extras or {}
    if set(additions) - set(packages):
        raise ValueError("Extra selections must name a selected package")
    captured = {}
    for name in packages:
        policy = registry.get("packages", {}).get(name)
        if policy is None or policy.get("status") != "active":
            raise ValueError(f"Unknown or inactive package: {name}")
        source = (Path(sources) / name).resolve(strict=True)
        if _git(source, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError(
                f"{name}: uncommitted inputs; commit or preserve them first"
            )
        revision = _git(source, "rev-parse", "HEAD")
        version, _, _, declared_extras = _metadata(source, revision, name)
        selected_extras = list(
            dict.fromkeys([*policy.get("extras", []), *additions.get(name, [])])
        )
        if any(
            canonicalize_name(extra) not in declared_extras for extra in selected_extras
        ):
            raise ValueError(
                f"{name}: requested extra is absent from committed metadata"
            )
        captured[name] = {
            "source": str(source),
            "revision": revision,
            "version": version,
            "extras": selected_extras,
        }
    manifest = {"format": 1, "kind": "candidate", "packages": captured}
    validate_cohort(manifest)
    return manifest


def validate_cohort(manifest):
    """Reject moving pins, changed checkouts and malformed candidate records."""
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("format")) is not int
        or manifest["format"] != 1
        or manifest.get("kind") != "candidate"
        or not isinstance(manifest.get("packages"), dict)
        or not manifest["packages"]
    ):
        raise ValueError("Expected a nonempty format-1 candidate cohort")
    normalized_names = set()
    for name, entry in manifest["packages"].items():
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", name
        ):
            raise ValueError("Invalid package name")
        normalized = canonicalize_name(name)
        if normalized in normalized_names:
            raise ValueError("Duplicate normalized package name")
        normalized_names.add(normalized)
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("revision"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", entry["revision"])
        ):
            raise ValueError(
                f"{name}: candidate revision must be a full immutable Git SHA"
            )
        if (
            not isinstance(entry.get("source"), str)
            or not Path(entry["source"]).is_absolute()
        ):
            raise ValueError(f"{name}: source must be an absolute checkout path")
        source = Path(entry["source"]).resolve(strict=True)
        if _git(source, "rev-parse", "HEAD") != entry["revision"]:
            raise ValueError(
                f"{name}: checkout revision changed since candidate capture"
            )
        if _git(source, "status", "--porcelain", "--untracked-files=all"):
            raise ValueError(f"{name}: uncommitted changes since candidate capture")
        version, _, _, declared_extras = _metadata(source, entry["revision"], name)
        if entry.get("version") != version:
            raise ValueError(
                f"{name}: candidate version differs from committed metadata"
            )
        extras = entry.get("extras")
        if (
            not isinstance(extras, list)
            or any(not isinstance(extra, str) for extra in extras)
            or len({canonicalize_name(extra) for extra in extras}) != len(extras)
            or any(canonicalize_name(extra) not in declared_extras for extra in extras)
        ):
            raise ValueError(f"{name}: invalid or unavailable extras")


def wheel_identity(path, name, version):
    """Check packaged distribution metadata and hash the actual wheel bytes."""
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        records = [
            item for item in archive.namelist() if item.endswith(".dist-info/METADATA")
        ]
        if len(records) != 1:
            raise ValueError(f"{path.name}: expected one distribution metadata file")
        metadata = Parser().parsestr(archive.read(records[0]).decode("utf-8"))
    if canonicalize_name(metadata.get("Name", "")) != canonicalize_name(name):
        raise ValueError(f"{path.name}: wheel name differs from captured package")
    if metadata.get("Version") != version:
        raise ValueError(f"{path.name}: wheel version differs from captured package")
    return {
        "filename": path.name,
        "version": version,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def execute(command, *, directory, log):
    """Run one bounded command without shell interpolation; retain its output."""
    with Path(log).open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            [str(argument) for argument in command],
            cwd=directory,
            env=clean_environment(),
            stdout=stream,
            stderr=subprocess.STDOUT,
            timeout=1800,
            check=False,
        )
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}")


def _archive(entry, directory):
    payload = subprocess.check_output(
        [
            "git",
            "-C",
            entry["source"],
            "archive",
            "--format=tar",
            entry["revision"],
        ]
    )
    directory.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
        archive.extractall(directory, filter="data")


def _import_probe(packages):
    # Every imported owner must live inside this environment, with matching
    # distribution metadata. Isolated mode also excludes the scenario's cwd.
    return "\n".join(
        [
            "import importlib, importlib.metadata, json, pathlib, sys",
            f"expected = {repr({name: entry['version'] for name, entry in packages.items()})}",
            "observed = {}",
            "for name, version in expected.items():",
            "    module = importlib.import_module(name)",
            "    path = pathlib.Path(module.__file__).resolve()",
            "    assert path.is_relative_to(pathlib.Path(sys.prefix).resolve()), (name, str(path))",
            "    assert 'site-packages' in path.parts, (name, str(path))",
            "    actual = importlib.metadata.version(name)",
            "    assert actual == version, (name, actual, version)",
            "    observed[name] = {'version': actual, 'import_path': str(path)}",
            "print(json.dumps({'python': sys.version, 'packages': observed}, indent=2))",
        ]
    )


def verify_cohort(
    manifest,
    directory,
    *,
    python=sys.executable,
    scenarios=(),
    requirements=None,
    dependency_wheels=None,
    no_index=False,
):
    """Build archived sources, install all wheels together, and run selected gates.

    The caller owns a new output directory. Third-party requirements may come
    from the normal configured index or an explicit dependency wheel directory.
    Failure retains a receipt and logs; it cannot replace an older verification.
    Scientific gates are named scripts, not arbitrary shell commands. Each gate
    owns its real prerequisites and must fail when a required resource is absent.
    """
    unknown = set(scenarios) - SCENARIOS.keys()
    if unknown:
        raise ValueError(f"Unknown scenario: {sorted(unknown)}")
    if len(set(scenarios)) != len(scenarios):
        raise ValueError("Select each scenario once")
    validate_cohort(manifest)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    logs = directory / "logs"
    logs.mkdir()
    wheels = directory / "wheels"
    wheels.mkdir()
    receipt = {
        "format": 1,
        "kind": "candidate-verification",
        "status": "running",
        "manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True).encode()
        ).hexdigest(),
        "packages": manifest["packages"],
        "wheels": {},
        "stages": [],
        "scenarios": {
            name: {"required": True, "status": "not_run"} for name in scenarios
        },
    }
    candidate = directory / "candidate.json"
    candidate.write_text(json.dumps(manifest, indent=2) + "\n")

    def run(label, command):
        log = logs / f"{label}.log"
        stage = {
            "name": label,
            "command": [str(arg) for arg in command],
            "log": str(log),
            "status": "running",
        }
        receipt["stages"].append(stage)
        try:
            execute(command, directory=directory, log=log)
        except Exception:
            stage["status"] = "failed"
            raise
        stage["status"] = "passed"
        return log

    try:
        run("builder-runtime", [python, "-I", "--version"])
        built = []
        for name, entry in manifest["packages"].items():
            source = directory / "sources" / name
            _archive(entry, source)
            before = set(wheels.glob("*.whl"))
            run(
                f"build-{name}",
                [
                    python,
                    "-I",
                    "-m",
                    "pip",
                    "wheel",
                    "--no-deps",
                    "--no-build-isolation",
                    "--no-cache-dir",
                    "--wheel-dir",
                    wheels,
                    source,
                ],
            )
            produced = set(wheels.glob("*.whl")) - before
            if len(produced) != 1:
                raise ValueError(f"{name}: expected one built candidate wheel")
            wheel = produced.pop()
            receipt["wheels"][name] = wheel_identity(wheel, name, entry["version"])
            suffix = f"[{','.join(entry['extras'])}]" if entry["extras"] else ""
            built.append(str(wheel) + suffix)
        environment = directory / "environment"
        run("create-environment", [python, "-I", "-m", "venv", environment])
        worker = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        install = [worker, "-I", "-m", "pip", "install", "--find-links", wheels]
        if dependency_wheels is not None:
            install.extend(
                ["--find-links", Path(dependency_wheels).resolve(strict=True)]
            )
        if no_index:
            install.append("--no-index")
        if requirements is not None:
            install.extend(["-r", Path(requirements).resolve(strict=True)])
        run("install", [*install, *built])
        run("dependency-consistency", [worker, "-I", "-m", "pip", "check"])
        inventory = run(
            "dependency-inventory", [worker, "-I", "-m", "pip", "freeze", "--all"]
        )
        receipt["dependency_inventory"] = {
            "path": str(inventory.relative_to(directory)),
            "sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
        }
        probe = run(
            "installed-imports",
            [worker, "-I", "-c", _import_probe(manifest["packages"])],
        )
        receipt["installed"] = json.loads(probe.read_text())
        for name in scenarios:
            receipt["scenarios"][name]["status"] = "running"
            epsm = directory / "sources" / "epsm"
            script = epsm / SCENARIOS[name]
            try:
                if not script.is_file():
                    raise ValueError(
                        f"Required scenario is absent from the captured EPSM source: {name}"
                    )
                command = scenario_command(
                    name,
                    worker,
                    epsm,
                    directory / "scenarios" / name,
                    candidate,
                    wheels,
                )
                run(f"scenario-{name}", command)
            except Exception:
                receipt["scenarios"][name]["status"] = "failed"
                raise
            receipt["scenarios"][name]["status"] = "passed"
        receipt["status"] = "passed"
    except Exception as error:
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        raise
    finally:
        (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser(
        "capture", help="Capture clean committed candidate sources"
    )
    capture.add_argument("--sources", type=Path, required=True)
    capture.add_argument("--packages", nargs="+")
    capture.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="PACKAGE:EXTRA",
        help="Add a declared package extra without changing registry defaults",
    )
    capture.add_argument(
        "--registry",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "platform-registry.json",
    )
    capture.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser(
        "verify", help="Build/install candidates and retain selected gate evidence"
    )
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--directory", type=Path, required=True)
    verify.add_argument("--python", default=sys.executable)
    verify.add_argument(
        "--scenario", action="append", choices=sorted(SCENARIOS), default=[]
    )
    verify.add_argument("--requirements", type=Path)
    verify.add_argument("--dependency-wheels", type=Path)
    verify.add_argument("--no-index", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            policy = _load_json(args.registry)
            packages = args.packages or [
                name
                for name, entry in policy["packages"].items()
                if entry.get("status") == "active"
                and entry.get("role", "scientific") == "scientific"
            ]
            additions = {}
            for selection in args.extra:
                parts = selection.split(":")
                if len(parts) != 2 or not all(parts):
                    raise ValueError("Extra selections use PACKAGE:EXTRA")
                additions.setdefault(parts[0], []).append(parts[1])
            manifest = capture_cohort(args.sources, packages, policy, extras=additions)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x") as stream:
                stream.write(json.dumps(manifest, indent=2) + "\n")
            print(args.output)
        else:
            verify_cohort(
                _load_json(args.manifest),
                args.directory,
                python=args.python,
                scenarios=args.scenario,
                requirements=args.requirements,
                dependency_wheels=args.dependency_wheels,
                no_index=args.no_index,
            )
            print(args.directory / "receipt.json")
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Candidate check failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
