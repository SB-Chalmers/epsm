# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Record the exact wheel combination used by coordinated logging checks."""

import argparse
import importlib
import json
import platform
import subprocess
from importlib import metadata
from pathlib import Path


def collect_logging(root, manifest, *, sources_root=None, mode="pinned"):
    """Require installed wheels and record the selected source revisions.

    Routine checks enforce the supported pins. Explicit main-candidate checks
    retain the actual revisions and versions without changing those pins.
    """
    if mode not in {"pinned", "main"}:
        raise ValueError("Logging mode must be pinned or main")
    root = Path(root)
    sources_root = Path(sources_root) if sources_root is not None else root / ".ci"
    packages = {}
    for name, expected in manifest["packages"].items():
        if expected.get("role", "scientific") == "display":
            continue
        revision = expected["revision"]
        source = root if name == "epsm" else sources_root / name
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        if mode == "pinned" and name != "epsm" and actual != revision:
            raise RuntimeError(f"Unexpected source revision for {name}: {actual}")
        version = metadata.version(name)
        if mode == "pinned" and version != expected["version"]:
            raise RuntimeError(
                f"Unexpected installed version for {name}: {version}, "
                f"expected {expected['version']}"
            )
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        direct = metadata.distribution(name).read_text("direct_url.json")
        editable = bool(
            direct and json.loads(direct).get("dir_info", {}).get("editable")
        )
        if "site-packages" not in path.parts or editable:
            raise RuntimeError(
                f"{name} did not import from its installed wheel: {path}"
            )
        packages[name] = {
            "version": version,
            "import_path": str(path),
            "revision": actual,
            "editable": editable,
        }
    return {
        "schema_version": 1,
        "mode": mode,
        "python": platform.python_version(),
        "packages": packages,
    }


def main():
    """Require installed libraries and retain versions, import paths and revisions."""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-root", type=Path, default=root / ".ci")
    parser.add_argument("--mode", choices=("pinned", "main"), default="pinned")
    args = parser.parse_args()
    manifest = json.loads((root / "compatibility.json").read_text())
    result = collect_logging(
        root, manifest, sources_root=args.sources_root, mode=args.mode
    )
    output = root / "build/logging-verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(output)


if __name__ == "__main__":
    main()
