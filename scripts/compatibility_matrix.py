"""Emit pinned or explicitly requested main-dependency GitHub matrix entries."""

import argparse
import json
import re
from pathlib import Path

DEFAULT_PYTHON = ("3.11", "3.13")


def build_matrix(
    manifest,
    *,
    mode="pinned",
    consumer=None,
    packages=None,
    manifest_revision=None,
    candidate_revision=None,
    consumer_revision=None,
):
    """Select routine pinned lanes or one opt-in main lane without changing pins.

    Platform entries contain ``version``/``revision`` mappings. Historical
    revision-only manifests are readable too; they use the supported Python
    defaults when they do not declare a Python list. EPSM itself is the workflow
    checkout, so it needs no second matrix-controlled checkout.
    """
    if mode not in {"pinned", "main"}:
        raise ValueError("Matrix mode must be pinned or main")
    cohort = manifest.get("packages")
    if not isinstance(cohort, dict) or not cohort:
        raise ValueError("Manifest must declare package revisions")
    if consumer is not None and consumer not in cohort:
        raise ValueError(f"Unknown consumer: {consumer}")
    if manifest_revision is not None and not re.fullmatch(
        r"[0-9a-f]{40}", manifest_revision
    ):
        raise ValueError("--manifest-revision must be the captured manifest Git SHA-40")
    if candidate_revision:
        if not re.fullmatch(r"[0-9a-f]{40}", candidate_revision):
            raise ValueError(
                "Candidate selection requires an immutable EPSM Git SHA-40"
            )
        if mode != "pinned":
            raise ValueError("A candidate cohort requires pinned mode")
        if candidate_revision != manifest_revision:
            raise ValueError(
                "Candidate manifest checkout differs from requested revision"
            )
        if manifest.get("kind") != "candidate":
            raise ValueError(
                "Explicit candidate selection requires a candidate manifest"
            )
        own = cohort.get(consumer or "epsm", {})
        expected = own.get("revision") if isinstance(own, dict) else own
        expected = candidate_revision if expected == "self" else expected
        if consumer_revision != expected:
            raise ValueError(
                "Candidate consumer checkout differs from its captured revision"
            )
    selected = (
        set(packages)
        if packages is not None
        else {
            name
            for name, entry in cohort.items()
            if not isinstance(entry, dict)
            or entry.get("role", "scientific") == "scientific"
        }
    )
    if selected - cohort.keys():
        raise ValueError(f"Unknown dependencies: {sorted(selected - cohort.keys())}")
    refs = {}
    for name, package in cohort.items():
        revision = package.get("revision") if isinstance(package, dict) else package
        if not isinstance(revision, str) or not (
            (name == "epsm" and revision == "self")
            or re.fullmatch(r"[0-9a-f]{40}", revision)
        ):
            raise ValueError(
                f"{name}: an immutable package revision is required (self only for epsm)"
            )
        if isinstance(package, dict) and package.get("role", "scientific") not in {
            "scientific",
            "display",
        }:
            raise ValueError(f"{name}: role must be scientific or display")
        if name not in selected or name == (consumer or "epsm"):
            continue
        if revision == "self":
            if manifest_revision is None:
                raise ValueError("Resolving EPSM self requires --manifest-revision")
            revision = manifest_revision
        refs[name] = revision if mode == "pinned" else "main"
    versions = manifest.get("python", DEFAULT_PYTHON)
    if not isinstance(versions, (list, tuple)) or not versions:
        raise ValueError("Manifest must declare a nonempty Python version list")
    if any(not isinstance(version, str) or not version.strip() for version in versions):
        raise ValueError("Python versions must be nonempty strings")
    if mode == "main":
        if "3.13" not in versions:
            raise ValueError("Main-dependency checks require Python 3.13 support")
        versions = ("3.13",)
    provenance = {"manifest_revision": manifest_revision} if manifest_revision else {}
    if candidate_revision:
        provenance.update(cohort="candidate", consumer_revision=consumer_revision)
    return {
        "include": [
            {"python": python, "mode": mode, **provenance, **refs}
            for python in versions
        ]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "compatibility.json",
        help="Package combination JSON (default: the repository's compatibility.json)",
    )
    parser.add_argument("--mode", choices=("pinned", "main"), default="pinned")
    parser.add_argument(
        "--consumer", help="Keep this package's own checkout under test"
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        help="Dependency names; defaults to scientific packages",
    )
    parser.add_argument(
        "--manifest-revision", help="Captured Git SHA of the EPSM manifest checkout"
    )
    parser.add_argument(
        "--candidate-revision",
        help="Explicit immutable candidate manifest checkout SHA",
    )
    parser.add_argument(
        "--consumer-revision", help="Actual checkout SHA of the consumer under test"
    )
    args = parser.parse_args()
    try:
        matrix = build_matrix(
            json.loads(args.manifest.read_text()),
            mode=args.mode,
            consumer=args.consumer,
            packages=args.packages,
            manifest_revision=args.manifest_revision,
            candidate_revision=args.candidate_revision,
            consumer_revision=args.consumer_revision,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("matrix=" + json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
