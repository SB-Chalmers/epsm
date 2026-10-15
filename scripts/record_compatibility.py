"""Record exact checked-out revisions, installed versions and producer environment."""

import argparse
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pinned", "dev"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "compatibility.json").read_text())
    observed = {}
    for name, expected in manifest["packages"].items():
        source = root if name == "epsm" else root / ".ci" / name
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        version = importlib.metadata.version(name)
        if args.mode == "pinned":
            if expected["revision"] != "self" and revision != expected["revision"]:
                raise RuntimeError(f"{name}: unexpected source revision {revision}")
            if version != expected["version"]:
                raise RuntimeError(
                    f"{name}: installed {version}, expected {expected['version']}"
                )
        observed[name] = {"revision": revision, "version": version}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "format": 1,
                "mode": args.mode,
                "python": platform.python_version(),
                "packages": observed,
            },
            indent=2,
        )
        + "\n"
    )
    print(args.output)


if __name__ == "__main__":
    main()
