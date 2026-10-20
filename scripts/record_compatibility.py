"""Record exact checked-out revisions, installed versions and producer environment."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path


def collect_receipt(root, manifest, *, mode, wheels=None, energyplus_exe=None):
    """Record installed scientific packages without requiring display dependencies."""
    root = Path(root)
    if mode not in {"pinned", "main"}:
        raise ValueError("Receipt mode must be pinned or main")
    manifest_revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()
    observed = {}
    for name, expected in manifest["packages"].items():
        if expected.get("role", "scientific") == "display":
            continue
        source = root if name == "epsm" else root / ".ci" / name
        revision = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True
        ).strip()
        version = importlib.metadata.version(name)
        if mode == "pinned":
            if expected["revision"] != "self" and revision != expected["revision"]:
                raise RuntimeError(f"{name}: unexpected source revision {revision}")
            if version != expected["version"]:
                raise RuntimeError(
                    f"{name}: installed {version}, expected {expected['version']}"
                )
        observed[name] = {"revision": revision, "version": version}
    result = {
        "format": 1,
        "mode": mode,
        "python": platform.python_version(),
        "manifest_revision": manifest_revision,
        "packages": observed,
    }
    if wheels is not None:
        artifacts = sorted(Path(wheels).glob("*.whl"))
        if not artifacts:
            raise ValueError("No release wheels found for the compatibility receipt")
        result["wheels"] = {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in artifacts
        }
    if energyplus_exe is not None:
        executable = Path(energyplus_exe).resolve(strict=True)
        version = subprocess.run(
            [str(executable), "--version"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        ).stdout.strip()
        with executable.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        result["energyplus"] = {
            "path": str(executable),
            "version": version,
            "sha256": digest,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pinned", "main"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--wheels", type=Path, help="Directory of actual built wheel artifacts"
    )
    parser.add_argument(
        "--energyplus-exe", type=Path, help="Actual executable identity"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "compatibility.json").read_text())
    result = collect_receipt(
        root,
        manifest,
        mode=args.mode,
        wheels=args.wheels,
        energyplus_exe=args.energyplus_exe,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            result,
            indent=2,
        )
        + "\n"
    )
    print(args.output)


if __name__ == "__main__":
    main()
