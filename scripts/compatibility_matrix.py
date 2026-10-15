"""Emit GitHub's matrix from the exact supported package combination."""

import json
from pathlib import Path


def main():
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "compatibility.json").read_text()
    )
    include = []
    for python in manifest["python"]:
        for mode in ("pinned", "dev"):
            refs = {
                name: package["revision"] if mode == "pinned" else "dev"
                for name, package in manifest["packages"].items()
                if name != "epsm"
            }
            include.append({"python": python, "mode": mode, **refs})
    print("matrix=" + json.dumps({"include": include}, separators=(",", ":")))


if __name__ == "__main__":
    main()
