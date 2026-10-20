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


def main():
    """Require installed libraries and retain versions, import paths and revisions."""
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-root", type=Path, default=root / ".ci")
    args = parser.parse_args()
    manifest = json.loads((root / "compatibility.json").read_text())
    packages = {}
    for name, expected in manifest["packages"].items():
        if expected.get("role", "scientific") == "display":
            continue
        revision = expected["revision"]
        source = root if name == "epsm" else args.sources_root / name
        actual = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        if name != "epsm" and actual != revision:
            raise RuntimeError(f"Unexpected source revision for {name}: {actual}")
        version = metadata.version(name)
        if version != expected["version"]:
            raise RuntimeError(
                f"Unexpected installed version for {name}: {version}, "
                f"expected {expected['version']}"
            )
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        if "site-packages" not in path.parts:
            raise RuntimeError(
                f"{name} did not import from its installed wheel: {path}"
            )
        packages[name] = {
            "version": version,
            "import_path": str(path),
            "revision": revision,
        }
    packages["epsm"]["revision"] = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    output = root / "build/logging-verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "python": platform.python_version(),
                "packages": packages,
            },
            indent=2,
        )
        + "\n"
    )
    print(output)


if __name__ == "__main__":
    main()
