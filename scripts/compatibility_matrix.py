"""Emit pinned or explicitly requested main-dependency GitHub matrix entries."""

import argparse
import json
from pathlib import Path

DEFAULT_PYTHON = ("3.11", "3.13")


def build_matrix(manifest, *, mode="pinned"):
    """Select routine pinned lanes or one opt-in main lane without changing pins.

    Platform entries contain ``version``/``revision`` mappings. Historical
    revision-only manifests are readable too; they use the supported Python
    defaults when they do not declare a Python list. EPSM itself is the workflow
    checkout, so it needs no second matrix-controlled checkout.
    """
    if mode not in {"pinned", "main"}:
        raise ValueError("Matrix mode must be pinned or main")
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise ValueError("Manifest must declare package revisions")
    refs = {}
    for name, package in packages.items():
        if name == "epsm":
            continue
        revision = package.get("revision") if isinstance(package, dict) else package
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError(f"{name}: a nonempty package revision is required")
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
    return {
        "include": [{"python": python, "mode": mode, **refs} for python in versions]
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
    args = parser.parse_args()
    try:
        matrix = build_matrix(json.loads(args.manifest.read_text()), mode=args.mode)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("matrix=" + json.dumps(matrix, separators=(",", ":")))


if __name__ == "__main__":
    main()
