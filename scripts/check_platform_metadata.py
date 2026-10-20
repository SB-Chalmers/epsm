# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Check committed platform metadata without installing or importing collaborators.

Pinned mode reads the supported commit blobs. Main mode resolves each checkout's
main ref once (falling back to detached HEAD in CI). Working files are never used
as package metadata. Passing this check establishes metadata agreement, not a
working scientific integration, and never changes the supported release pins.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import tomllib
from pathlib import Path, PurePosixPath

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version


def _git(source, *arguments):
    result = subprocess.run(
        ["git", "-C", str(source), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"Cannot read committed source: git {' '.join(arguments)}")
    return result.stdout.strip()


def _blob(source, revision, filename):
    path = PurePosixPath(filename)
    if path.is_absolute() or ".." in path.parts or "\\" in filename:
        raise ValueError(f"Metadata path must stay inside the repository: {filename}")
    return _git(source, "show", f"{revision}:{path.as_posix()}")


def _version(source, revision, metadata):
    project = metadata["project"]
    if "version" in project:
        value = project["version"]
    else:
        tool = metadata.get("tool", {})
        if not isinstance(tool, dict):
            raise ValueError("tool must be a table")
        configuration = tool.get("setuptools", {})
        if not isinstance(configuration, dict):
            raise ValueError("tool.setuptools must be a table")
        dynamic = configuration.get("dynamic", {})
        if not isinstance(dynamic, dict):
            raise ValueError("tool.setuptools.dynamic must be a table")
        definition = dynamic.get("version", {})
        if not isinstance(definition, dict):
            raise ValueError("Dynamic version definition must be a table")
        if "file" in definition:
            paths = definition["file"]
            if isinstance(paths, str):
                paths = [paths]
            if not isinstance(paths, list) or not paths:
                raise ValueError("Dynamic version file must name a repository file")
            value = "\n".join(_blob(source, revision, path) for path in paths).strip()
        elif "attr" in definition:
            if not isinstance(definition["attr"], str):
                raise ValueError("Dynamic version attribute must be a string")
            module, attribute = definition["attr"].rsplit(".", 1)
            if not all(part.isidentifier() for part in (*module.split("."), attribute)):
                raise ValueError(
                    "Dynamic version attribute must name a Python attribute"
                )
            module_path = module.replace(".", "/")
            package_dirs = configuration.get("package-dir", {})
            if not isinstance(package_dirs, dict):
                raise ValueError("tool.setuptools.package-dir must be a table")
            configured = package_dirs.get("")
            directories = dict.fromkeys([configured, "src", "", "python"])
            value = None
            for directory in directories:
                if directory is None:
                    continue
                for suffix in (".py", "/__init__.py"):
                    filename = str(PurePosixPath(directory) / (module_path + suffix))
                    try:
                        nodes = ast.parse(_blob(source, revision, filename)).body
                    except ValueError:
                        continue
                    assignments = []
                    for node in nodes:
                        targets = node.targets if isinstance(node, ast.Assign) else []
                        if isinstance(node, ast.AnnAssign):
                            targets = [node.target]
                        if (
                            any(
                                isinstance(t, ast.Name) and t.id == attribute
                                for t in targets
                            )
                            and node.value is not None
                        ):
                            assignments.append(node.value)
                    if len(assignments) > 1:
                        raise ValueError(
                            "Dynamic version attribute has multiple assignments"
                        )
                    if assignments:
                        value = ast.literal_eval(assignments[0])
                    if value is not None:
                        break
                if value is not None:
                    break
            if value is None:
                raise ValueError("Dynamic version attribute has no literal assignment")
        else:
            raise ValueError(
                "Version must be static, a literal setuptools attr, or a file"
            )
    if not isinstance(value, str):
        raise ValueError("Declared package version must be a string")
    return str(Version(value))


def _load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def constant(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    return json.loads(
        path.read_text(),
        object_pairs_hook=pairs,
        parse_constant=constant,
    )


def _policy(root):
    registry = _load_json(root / "platform-registry.json")
    supported = _load_json(root / "compatibility.json")
    for label, document in (("registry", registry), ("compatibility", supported)):
        if not isinstance(document, dict) or type(document.get("format")) is not int:
            raise ValueError(f"{label} must have integer format 1")
        if document["format"] != 1 or not isinstance(document.get("packages"), dict):
            raise ValueError(f"Unsupported {label} format or missing package mapping")
        if not document["packages"]:
            raise ValueError(f"{label} package mapping cannot be empty")
    python = supported.get("python")
    if (
        not isinstance(python, list)
        or not python
        or any(not isinstance(p, str) or not re.fullmatch(r"3\.\d+", p) for p in python)
        or len(set(python)) != len(python)
    ):
        raise ValueError("Supported Python versions must be unique major.minor strings")
    names = {}
    for name, entry in registry["packages"].items():
        normalized = canonicalize_name(name)
        if not re.fullmatch(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*", name):
            raise ValueError(f"Invalid package name: {name}")
        if normalized in names:
            raise ValueError(f"Duplicate normalized package name: {name}")
        names[normalized] = name
        if not isinstance(entry, dict) or entry.get("role", "scientific") not in {
            "scientific",
            "display",
        }:
            raise ValueError(f"{name}: role must be scientific or display")
        if not isinstance(entry, dict) or entry.get("status") not in {
            "active",
            "unpublished",
        }:
            raise ValueError(f"{name}: status must be active or unpublished")
        if entry.get("branch") != "main":
            raise ValueError(f"{name}: candidate branch must be main")
        extras = entry.get("extras")
        if (
            not isinstance(extras, list)
            or any(
                not isinstance(e, str) or not re.fullmatch(r"[\w.-]+", e)
                for e in extras
            )
            or len({canonicalize_name(e) for e in extras}) != len(extras)
        ):
            raise ValueError(f"{name}: extras must be a unique list of extra names")
        repository = entry.get("repository")
        if entry["status"] == "active" and (
            not isinstance(repository, str)
            or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository)
        ):
            raise ValueError(
                f"{name}: active package needs an owner/repository reference"
            )
        if entry["status"] == "unpublished" and repository is not None:
            raise ValueError(f"{name}: unpublished repository must be null")
    if "epsm" not in supported["packages"]:
        raise ValueError("Supported combination must include epsm")
    for name, pin in supported["packages"].items():
        if (
            name not in registry["packages"]
            or registry["packages"][name]["status"] != "active"
        ):
            raise ValueError(
                f"{name}: supported package must be active in the registry"
            )
        if not isinstance(pin, dict) or not isinstance(pin.get("version"), str):
            raise ValueError(f"{name}: supported pin needs a version and revision")
        if pin.get("role", "scientific") != registry["packages"][name].get(
            "role", "scientific"
        ):
            raise ValueError(f"{name}: supported role must match the registry")
        Version(pin["version"])
        revision = pin.get("revision")
        if not isinstance(revision, str) or not (
            (name == "epsm" and revision == "self")
            or re.fullmatch(r"[0-9a-f]{40}", revision)
        ):
            raise ValueError(
                f"{name}: supported revision must be SHA-40 (self only for epsm)"
            )
    return registry["packages"], supported


def _main_revision(source):
    for reference in ("refs/heads/main", "refs/remotes/origin/main"):
        try:
            return reference, _git(
                source, "rev-parse", "--verify", f"{reference}^{{commit}}"
            )
        except ValueError:
            continue
    try:
        _git(source, "symbolic-ref", "-q", "HEAD")
    except ValueError:
        return "HEAD", _git(source, "rev-parse", "--verify", "HEAD^{commit}")
    raise ValueError(
        "Checkout has no main ref; a feature branch cannot substitute for main"
    )


def _metadata(source, revision, expected_name):
    metadata = tomllib.loads(_blob(source, revision, "pyproject.toml"))
    project = metadata.get("project", {})
    if not isinstance(project, dict):
        raise ValueError("Project metadata must be a table")
    if canonicalize_name(project.get("name", "")) != canonicalize_name(expected_name):
        raise ValueError(f"Declared project name does not match {expected_name}")
    if set(project.get("dynamic", [])) & {"dependencies", "optional-dependencies"}:
        raise ValueError(
            "Dynamic dependencies require a build; this guard cannot verify them"
        )
    version = _version(source, revision, metadata)
    if expected_name == "epsm_viewer":
        npm = json.loads(_blob(source, revision, "package.json"))
        stored = _blob(source, revision, "VERSION").strip()
        if npm.get("version") != version or stored != version:
            raise ValueError(
                "Viewer package.json, VERSION and Python versions must agree"
            )
    python = project.get("requires-python", "")
    SpecifierSet(python)
    dependencies = project.get("dependencies", [])
    extras = project.get("optional-dependencies", {})
    if not isinstance(dependencies, list) or not isinstance(extras, dict):
        raise ValueError(
            "Dependencies must be a list and optional-dependencies a mapping"
        )
    parsed_extras = {}
    for name, requirements in extras.items():
        normalized = canonicalize_name(name)
        if normalized in parsed_extras:
            raise ValueError(f"Duplicate normalized extra name: {name}")
        if not isinstance(requirements, list):
            raise ValueError(f"Extra {name} requirements must be a list")
        parsed_extras[normalized] = [Requirement(r) for r in requirements]
    return version, python, [Requirement(r) for r in dependencies], parsed_extras


def check_platform(root: Path, sources: Path, mode: str = "pinned") -> dict:
    """Read local Git blobs and return a deterministic metadata-only report."""
    report = {
        "format": 1,
        "mode": mode,
        "status": "failed",
        "packages": {},
        "findings": [],
    }

    def finding(level, code, message, package=None):
        row = {"level": level, "code": code, "message": message}
        if package is not None:
            row["package"] = package
        if row not in report["findings"]:
            report["findings"].append(row)

    try:
        if mode not in {"pinned", "main"}:
            raise ValueError("Mode must be pinned or main")
        registry, supported = _policy(Path(root))
    except (ValueError, OSError, TypeError, KeyError) as error:
        finding("error", "policy_invalid", str(error))
        return report
    report["python"] = supported["python"]
    # This is the hosted Ubuntu/CPython platform, independent of the machine
    # running the guard. The installed release gate checks external dependencies.
    report["marker_environment"] = {
        "implementation_name": "cpython",
        "os_name": "posix",
        "platform_machine": "x86_64",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "platform_python_implementation": "CPython",
        "sys_platform": "linux",
    }
    metadata = {}
    for name, entry in sorted(registry.items()):
        pin = supported["packages"].get(name)
        row = {
            "repository": entry["repository"],
            "extras": sorted(entry["extras"]),
            "integration_status": "unverified",
        }
        report["packages"][name] = row
        if entry["status"] == "unpublished":
            row["status"] = "unpublished"
            finding(
                "warning",
                "unpublished_package",
                "Unpublished; no remote metadata checked",
                name,
            )
            continue
        if pin is None:
            finding(
                "warning",
                "unverified_package",
                "Package is outside the tested combination",
                name,
            )
            if mode == "pinned":
                row["status"] = "unpinned"
                continue
        source = Path(root) if name == "epsm" else Path(sources) / name
        row["status"] = "failed"
        if not source.is_dir():
            finding(
                "error",
                "checkout_missing",
                f"Required checkout is missing: {source}",
                name,
            )
            continue
        try:
            if mode == "main":
                reference, revision = _main_revision(source)
            else:
                reference = "HEAD" if pin["revision"] == "self" else pin["revision"]
                revision = _git(
                    source, "rev-parse", "--verify", f"{reference}^{{commit}}"
                )
            row.update(selected_ref=reference, revision=revision)
            version, python, dependencies, extras = _metadata(source, revision, name)
            selected = {canonicalize_name(e) for e in entry["extras"]}
            if selected - extras.keys():
                raise ValueError(
                    f"Selected extras are not declared: {sorted(selected - extras.keys())}"
                )
            metadata[name] = (dependencies, extras)
            row.update(
                status="checked",
                version=version,
                requires_python=python,
                effective_extras=sorted(selected),
            )
            if pin:
                row["supported"] = dict(pin)
                if mode == "pinned" and Version(version) != Version(pin["version"]):
                    finding(
                        "error",
                        "version_mismatch",
                        f"Committed version {version} differs from supported {pin['version']}",
                        name,
                    )
                if mode == "main" and (
                    Version(version) != Version(pin["version"])
                    or (pin["revision"] != "self" and revision != pin["revision"])
                ):
                    finding(
                        "info",
                        "candidate_drift",
                        "Main differs from the tested combination; integration remains unverified",
                        name,
                    )
            for target in supported["python"]:
                if Version(target) not in SpecifierSet(python):
                    finding(
                        "error",
                        "python_unsatisfied",
                        f"Python {target} does not satisfy {python}",
                        name,
                    )
        except (ValueError, TypeError, KeyError, SyntaxError, OSError) as error:
            finding("error", "metadata_invalid", str(error), name)
    _dependencies(report, registry, metadata, finding)
    report["findings"].sort(
        key=lambda f: (f["level"], f.get("package", ""), f["code"], f["message"])
    )
    report["status"] = (
        "failed" if any(f["level"] == "error" for f in report["findings"]) else "passed"
    )
    return report


def _dependencies(report, registry, metadata, finding):
    names = {canonicalize_name(name): name for name in registry}
    active_by_python = {
        (name, python): set(report["packages"][name]["effective_extras"])
        for name in metadata
        for python in report["python"]
    }
    all_requirements = {name: set() for name in metadata}
    # Requirements can activate extras on their target package. Iterate to a fixed
    # point; cycles such as EPSM -> LCA integration -> EPSM[rc] are legitimate.
    changed = True
    while changed:
        changed = False
        for name, (base, extras) in sorted(metadata.items()):
            row = report["packages"][name]
            for python in report["python"]:
                selected = sorted(active_by_python[name, python])
                requirements = [(r, extra) for r in base for extra in ["", *selected]]
                for extra in selected:
                    requirements.extend((r, extra) for r in extras[extra])
                all_requirements[name].update(str(r) for r, _ in requirements)
                for requirement, extra in requirements:
                    target_name = names.get(canonicalize_name(requirement.name))
                    environment = {
                        **report["marker_environment"],
                        "python_version": python,
                        "implementation_version": f"{python}.0",
                        "python_full_version": f"{python}.0",
                        "extra": extra,
                    }
                    if requirement.marker and not requirement.marker.evaluate(
                        environment
                    ):
                        continue
                    if target_name is None:
                        if canonicalize_name(requirement.name).startswith("epsm-"):
                            finding(
                                "error",
                                "dependency_unregistered",
                                f"Internal dependency {requirement.name} is absent from the registry",
                                name,
                            )
                        continue  # External packages are checked by the installed gate.
                    target = report["packages"][target_name]
                    if target.get("status") != "checked":
                        level = (
                            "warning" if target.get("status") == "unpinned" else "error"
                        )
                        finding(
                            level,
                            "dependency_unverified",
                            f"{requirement} has no checked metadata for Python {python}",
                            name,
                        )
                        continue
                    if (
                        requirement.url
                        or Version(target["version"]) not in requirement.specifier
                    ):
                        finding(
                            "error",
                            "dependency_unsatisfied",
                            f"{requirement} is not satisfied by {target_name} {target['version']} on Python {python}",
                            name,
                        )
                    requested = {canonicalize_name(e) for e in requirement.extras}
                    missing = requested - metadata[target_name][1].keys()
                    if missing:
                        finding(
                            "error",
                            "dependency_extra_missing",
                            f"{target_name} does not declare requested extras: {sorted(missing)}",
                            name,
                        )
                    new = requested - missing - active_by_python[target_name, python]
                    if new:
                        active_by_python[target_name, python].update(new)
                        changed = True
    for name in metadata:
        row = report["packages"][name]
        row["effective_extras"] = sorted(
            set().union(
                *(active_by_python[name, python] for python in report["python"])
            )
        )
        row["requirements"] = sorted(all_requirements[name])


def render_summary(report: dict) -> str:
    """Render the report with explicit limits on metadata-only evidence."""
    lines = [
        f"# Platform metadata ({report['mode']})",
        "",
        f"Metadata status: **{report['status']}**. Scientific integration was not executed.",
        "",
        "| Package | Version | Revision | Metadata state |",
        "| --- | --- | --- | --- |",
    ]
    for name, row in sorted(report["packages"].items()):
        lines.append(
            f"| {name} | {row.get('version', '—')} | {row.get('revision', '—')} | {row['status']} |"
        )
    if report["findings"]:
        lines += ["", "Findings:", ""]
        for row in report["findings"]:
            package = f"{row['package']}: " if "package" in row else ""
            message = row["message"].replace("\n", " ").replace("|", "\\|")
            lines.append(f"- **{row['level']}** `{row['code']}`: {package}{message}")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    """Write requested reports and return nonzero when metadata checks fail."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--mode", choices=("pinned", "main"), default="pinned")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)
    report = check_platform(args.root, args.sources or args.root / ".ci", args.mode)
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    for path, contents in (
        (args.output, encoded),
        (args.summary, render_summary(report)),
    ):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
