# File: audit_ci_references.py
# Purpose: Audit captured CI checkout pins and literal own-wheel versions as metadata.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: MIT; see the project-root LICENSE.
# Date created: 2026-10-20
# Date modified: 2026-10-20
"""Read committed workflows without checking out or executing their source.

Old checkout pins can be deliberate owner-tested combinations. They are warnings,
not failed integration tests. Dynamic expressions remain unverified. Only invalid
inputs, unavailable captured revisions and definite own-wheel version mismatches
fail this audit. It never updates a pin, starts CI or contacts a service.
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml
from packaging.utils import (
    InvalidWheelFilename,
    canonicalize_name,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
WHEEL = re.compile(r"(?<![A-Za-z0-9_])[A-Za-z0-9_]+-[^\s'\"/]+\.whl\b")


def _git(source, *arguments):
    """Read local Git objects; never import or execute package source."""
    result = subprocess.run(
        ["git", "-C", str(source), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(
            result.stderr.strip() or "Captured Git revision is unavailable"
        )
    return result.stdout


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def audit_references(root, sources, metadata):
    """Audit workflow blobs at the exact revisions in a metadata-checker report.

    Parameters
    ----------
    root : pathlib.Path
        EPSM root containing platform-registry.json and compatibility.json.
    sources : pathlib.Path
        Container of explicitly supplied collaborator repositories, named by package.
    metadata : dict
        Checker report with per-package revision SHA and parsed version. Failed or
        unpublished metadata rows remain unverified; checked rows require a full SHA.

    Returns
    -------
    dict
        References, findings and metadata-only status. Numerical and installed-package
        validation are not run, and supported pins are never changed.
    """
    root, sources = Path(root), Path(sources)
    report = {
        "format": 1,
        "scope": "captured_workflow_references_only",
        "runtime_validation": "not_run",
        "metadata_report_status": metadata.get("status")
        if isinstance(metadata, dict)
        else None,
        "references": [],
        "findings": [],
    }

    def finding(code, message, *, severity="error", **location):
        report["findings"].append(
            dict(code=code, severity=severity, message=message, **location)
        )

    try:
        registry = _mapping(
            json.loads((root / "platform-registry.json").read_text()), "Registry"
        )
        policy = _mapping(
            json.loads((root / "compatibility.json").read_text()),
            "Compatibility policy",
        )
        packages = _mapping(registry.get("packages"), "Registry packages")
        supported = _mapping(policy.get("packages"), "Supported packages")
        observed = _mapping(
            _mapping(metadata, "Metadata report").get("packages"), "Observed packages"
        )
        for name, pin in supported.items():
            _mapping(pin, f"Supported package {name}")
        for name, row in observed.items():
            _mapping(row, f"Observed package {name}")
            if row.get("status", "checked") not in {
                "checked",
                "failed",
                "unpinned",
                "unpublished",
            }:
                raise ValueError(f"Observed package {name} has an unsupported status")
        repositories = {}
        for name, entry in packages.items():
            _mapping(entry, f"Registry package {name}")
            repository = entry.get("repository")
            if repository is not None and not isinstance(repository, str):
                raise ValueError(
                    f"Registry repository for {name} must be a string or null"
                )
            if repository and repository.startswith("SB-Chalmers/"):
                repositories[repository.lower()] = name
        exceptions = registry.get("ci_reference_exceptions", [])
        if not isinstance(exceptions, list):
            raise ValueError("CI reference exceptions must be an array")
        for exception in exceptions:
            _mapping(exception, "CI reference exception")
            if any(
                not isinstance(exception.get(key), str) or not exception[key]
                for key in ("package", "workflow", "path", "revision", "reason")
            ):
                raise ValueError(
                    "CI reference exceptions require package/workflow/path/revision/reason"
                )
            if not SHA.fullmatch(exception["revision"]):
                raise ValueError("CI reference exceptions require a full revision SHA")
    except (OSError, ValueError, TypeError) as error:
        finding("invalid_input", str(error))
        report["status"] = "failed"
        return report

    for owner, entry in packages.items():
        if entry.get("status") == "unpublished":
            continue
        row = observed.get(owner)
        if not isinstance(row, dict):
            finding(
                "missing_revision",
                "Package has no captured metadata row",
                package=owner,
            )
            continue
        if row.get("status", "checked") != "checked":
            finding(
                "source_unverified",
                "Metadata source was not checked; workflows remain unverified",
                severity="info",
                package=owner,
            )
            continue
        revision, version = row.get("revision"), row.get("version")
        if not isinstance(revision, str) or not SHA.fullmatch(revision):
            finding(
                "missing_revision",
                "Checked package requires its captured full revision SHA",
                package=owner,
            )
            continue
        try:
            own_version = Version(version)
        except (InvalidVersion, TypeError):
            finding(
                "invalid_version",
                "Checked package requires its parsed version",
                package=owner,
            )
            continue
        source = root if owner == "epsm" else sources / owner
        try:
            paths = _git(
                source,
                "ls-tree",
                "-r",
                "--name-only",
                revision,
                "--",
                ".github/workflows",
            ).splitlines()
        except ValueError as error:
            finding("missing_revision", str(error), package=owner, revision=revision)
            continue
        for path in paths:
            if not path.endswith((".yml", ".yaml")):
                continue
            try:
                workflow = _mapping(
                    yaml.load(
                        _git(source, "show", f"{revision}:{path}"),
                        Loader=yaml.BaseLoader,
                    ),
                    "Workflow",
                )
                jobs = _mapping(workflow.get("jobs"), "Workflow jobs")
                for job_name, job in jobs.items():
                    _mapping(job, "Workflow job")
                    steps = job.get("steps", [])  # Reusable workflows need no steps.
                    if not isinstance(steps, list):
                        raise ValueError("Workflow steps must be an array")
                    for index, step in enumerate(steps, 1):
                        _mapping(step, "Workflow step")
                        location = dict(
                            package=owner, workflow=path, job=job_name, step=index
                        )
                        if (
                            str(step.get("uses", "")).split("@", 1)[0].lower()
                            == "actions/checkout"
                        ):
                            options = _mapping(step.get("with", {}), "Checkout options")
                            repository = options.get(
                                "repository", entry.get("repository")
                            )
                            if (
                                not isinstance(repository, str)
                                or repository.lower() not in repositories
                            ):
                                continue
                            # Default checkout of the owning workflow has no explicit pin.
                            if "ref" not in options and "repository" not in options:
                                continue
                            target = repositories[repository.lower()]
                            ref = options.get("ref")
                            reference = dict(
                                **location,
                                target_package=target,
                                repository=repository,
                                ref=ref,
                                path=options.get("path", ""),
                            )
                            if isinstance(ref, str) and SHA.fullmatch(ref):
                                exception = next(
                                    (
                                        item
                                        for item in exceptions
                                        if item["package"] == owner
                                        and item["workflow"] == path
                                        and item["path"] == options.get("path", "")
                                        and item["revision"].lower() == ref.lower()
                                    ),
                                    None,
                                )
                                observed_target = observed.get(target, {})
                                supported_target = supported.get(target, {})
                                if exception:
                                    classification, severity, reason = (
                                        "intentional_baseline",
                                        "info",
                                        exception["reason"],
                                    )
                                elif (
                                    ref.lower()
                                    == str(observed_target.get("revision", "")).lower()
                                ):
                                    classification, severity, reason = (
                                        "current_main",
                                        "info",
                                        "Matches captured candidate revision",
                                    )
                                elif (
                                    ref.lower()
                                    == str(supported_target.get("revision", "")).lower()
                                ):
                                    classification, severity, reason = (
                                        "supported_pin",
                                        "info",
                                        "Matches supported compatibility pin",
                                    )
                                else:
                                    classification, severity, reason = (
                                        "outside_baseline",
                                        "warning",
                                        "Outside captured main and supported pins; may be an intentional owner-tested set",
                                    )
                            else:
                                classification, severity, reason = (
                                    "unverified",
                                    "info",
                                    "Default/branch/tag/expression reference is not evaluated by this audit",
                                )
                            reference.update(
                                classification=classification,
                                severity=severity,
                                reason=reason,
                            )
                            report["references"].append(reference)
                        run = step.get("run", "")
                        if not isinstance(run, str):
                            raise ValueError("Workflow run must be a string")
                        for filename in WHEEL.findall(run):
                            try:
                                distribution, wheel_version, _, _ = (
                                    parse_wheel_filename(filename)
                                )
                            except InvalidWheelFilename:
                                continue  # Globs and expressions are not definite literal versions.
                            if (
                                distribution == canonicalize_name(owner)
                                and wheel_version != own_version
                            ):
                                finding(
                                    "wheel_version_mismatch",
                                    f"Own wheel {filename} disagrees with captured package version {version}",
                                    **location,
                                    revision=revision,
                                    wheel=filename,
                                    expected_version=version,
                                )
            except (ValueError, TypeError, yaml.YAMLError) as error:
                finding(
                    "invalid_workflow",
                    str(error),
                    package=owner,
                    workflow=path,
                    revision=revision,
                )
    report["status"] = (
        "failed"
        if any(row["severity"] == "error" for row in report["findings"])
        else "passed"
    )
    return report


def markdown_summary(report):
    """Describe static evidence without presenting it as a runtime test pass."""
    counts = {}
    for row in report["references"]:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    lines = [
        "",
        "### CI reference metadata audit",
        "",
        f"Status: **{report['status']}**. Runtime/integration tests: **not run**.",
        "Dynamic refs remain unverified; outside-baseline pins are review warnings, not automatic update instructions.",
        "",
        ", ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
        or "No scoped checkout references found.",
    ]
    for row in report["references"]:
        if row["severity"] == "warning":
            lines.append(
                f"- Review `{row['package']}/{row['workflow']}` → `{row['target_package']}`: `{row['ref']}` ({row['classification']})."
            )
    for row in report["findings"]:
        lines.append(
            f"- {row['severity']}: `{row.get('package', 'input')}` {row['message']}"
        )
    return "\n".join(lines) + "\n"


def main(argv=None):
    """Read captured metadata, optionally write JSON and append a Markdown summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--sources", type=Path)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)
    try:
        metadata = json.loads(args.metadata.read_text())
        report = audit_references(
            args.root, args.sources or args.root / ".ci", metadata
        )
        text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    "w", dir=args.output.parent, delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    stream.write(text)
                os.replace(temporary, args.output)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        else:
            print(text, end="")
        if args.summary:
            with args.summary.open("a") as stream:
                stream.write(markdown_summary(report))
        return 0 if report["status"] == "passed" else 1
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f"CI reference audit failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
