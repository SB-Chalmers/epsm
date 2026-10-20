# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Sanjay Somanath
"""Render only the current README compatibility table from its tested manifest."""

import argparse
import json
import re
import sys
from pathlib import Path

START = "<!-- compatibility-table:start -->"
END = "<!-- compatibility-table:end -->"


def render_table(manifest):
    """Return a stable Markdown table of package names, versions and full revisions."""
    packages = manifest.get("packages") if isinstance(manifest, dict) else None
    if not isinstance(packages, dict) or not packages:
        raise ValueError("Compatibility manifest must declare packages")
    lines = ["| Package | Version | Tested commit |", "| --- | --- | --- |"]
    for name, package in sorted(packages.items()):
        if not isinstance(package, dict):
            raise ValueError(f"{name}: expected version and revision fields")
        version = package.get("version")
        revision = package.get("revision")
        if not isinstance(version, str) or not version.strip():
            raise ValueError(f"{name}: a package version is required")
        if not isinstance(revision, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40}|self", revision
        ):
            raise ValueError(f"{name}: a full commit revision or self is required")
        lines.append(f"| `{name}` | {version} | `{revision}` |")
    return "\n".join(lines)


def replace_table(readme, table):
    """Replace one marked table, preserving all text outside its marker lines."""
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError(
            "README must contain exactly one start and one end table marker"
        )
    start = re.search(rf"^{re.escape(START)}[ \t]*(\r?\n)", readme, re.MULTILINE)
    end = re.search(rf"^{re.escape(END)}[ \t]*(?:\r?\n|$)", readme, re.MULTILINE)
    if not start or not end or end.start() < start.end():
        raise ValueError(
            "README table markers must be separate lines in start/end order"
        )
    newline = start.group(1)
    return (
        readme[: start.end()]
        + table.replace("\n", newline)
        + newline
        + readme[end.start() :]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="EPSM repository root (default: this script's repository)",
    )
    parser.add_argument(
        "--check", action="store_true", help="Report drift without writing"
    )
    args = parser.parse_args()
    readme_path = args.root / "README.md"
    try:
        manifest = json.loads((args.root / "compatibility.json").read_bytes())
        original = readme_path.read_bytes()
        updated = replace_table(
            original.decode("utf-8"), render_table(manifest)
        ).encode("utf-8")
        if original != updated:
            if args.check:
                print(
                    "README compatibility table is out of date. "
                    "Run python scripts/render_compatibility.py to update it.",
                    file=sys.stderr,
                )
                return 1
            readme_path.write_bytes(updated)
            print(f"Updated {readme_path}")
        else:
            print("README compatibility table matches compatibility.json")
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
