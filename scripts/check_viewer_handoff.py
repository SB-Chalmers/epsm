# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Require installed Core scene data to pass Python and JavaScript Viewer APIs.

This explicit display check writes a scene and receipt, uses a temporary static
Viewer bundle, and starts Node with a 30-second timeout. It launches no browser,
server, engine or database. It belongs in a separate display environment.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

JAVASCRIPT_CHECK = """
import {prepareScene} from 'epsm_viewer/geometry';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const scene = JSON.parse(input);
const before = JSON.stringify(scene);
const rendered = prepareScene(scene);
if (JSON.stringify(scene) !== before) throw Error('Scene input was mutated');
for (const [index, source] of scene.objects.entries()) {
  const drawing = rendered.objects[index];
  if (drawing.id !== source.id || JSON.stringify(drawing.metadata) !== JSON.stringify(source.metadata))
    throw Error('Producer identity or metadata changed');
}
let triangleCount = 0;
for (const object of rendered.objects) {
  if (object.triangles.length % 9 || object.triangles.some(value => !Number.isFinite(value)))
    throw Error('Invalid drawing triangles');
  triangleCount += object.triangles.length / 9;
}
console.log(JSON.stringify({
  schema: rendered.schema, units: rendered.units, up_axis: rendered.up_axis,
  object_ids: rendered.objects.map(object => object.id),
  triangle_count: triangleCount, node_version: process.version,
}));
"""


def read_combination(path, core_revision, viewer_revision):
    """Match captured source checkouts to the central immutable display pins."""
    packages = json.loads(Path(path).read_text())["packages"]
    selected = {}
    for name, revision in (
        ("epsm_core", core_revision),
        ("epsm_viewer", viewer_revision),
    ):
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise RuntimeError(f"{name} requires a captured source SHA-40")
        row = packages.get(name)
        if not isinstance(row, dict) or not row.get("version"):
            raise RuntimeError(f"Manifest requires {name} version and revision")
        if row.get("revision") != revision:
            raise RuntimeError(f"{name} checkout does not match the supported manifest")
        selected[name] = {"version": row["version"], "revision": revision}
    return selected


def installed_package(name, expected):
    """Require an actual installed wheel with the declared manifest version."""
    version = metadata.version(name)
    if version != expected["version"]:
        raise RuntimeError(
            f"Installed {name} version does not match the manifest: {version}"
        )
    module = importlib.import_module(name)
    path = Path(module.__file__).resolve()
    direct = metadata.distribution(name).read_text("direct_url.json")
    editable = bool(direct and json.loads(direct).get("dir_info", {}).get("editable"))
    if "site-packages" not in path.parts or editable:
        raise RuntimeError(f"Installed wheel required for {name}: {path}")
    return {**expected, "import_path": str(path), "editable": editable}


def prepare_javascript_scene(scene, root, node, expected_version):
    """Pass the actual scene through the package's public geometry export."""
    root = Path(root).resolve()
    package = json.loads((root / "package.json").read_text())
    if (
        package.get("name") != "epsm_viewer"
        or package.get("version") != expected_version
    ):
        raise RuntimeError(
            "Built JavaScript Viewer version does not match installed Python Viewer"
        )
    try:
        result = subprocess.run(
            [str(node), "--input-type=module", "-e", JAVASCRIPT_CHECK],
            cwd=root,
            input=json.dumps(scene, allow_nan=False),
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        raise RuntimeError(
            f"Required JavaScript scene handoff failed: {detail}"
        ) from error
    drawing = json.loads(result.stdout)
    if drawing.get("object_ids") != [obj["id"] for obj in scene["objects"]]:
        raise RuntimeError("JavaScript Viewer changed source object identities")
    if any(drawing.get(key) != scene[key] for key in ("schema", "units", "up_axis")):
        raise RuntimeError("JavaScript Viewer changed scene format, units or axis")
    if (
        not isinstance(drawing.get("triangle_count"), int)
        or drawing["triangle_count"] <= 0
    ):
        raise RuntimeError("JavaScript Viewer produced no finite drawing triangles")
    return drawing


def run_handoff(args):
    """Capture one synthetic public Core scene and require both Viewer consumers."""
    selected = read_combination(args.manifest, args.core_revision, args.viewer_revision)
    packages = {
        name: installed_package(name, expected) for name, expected in selected.items()
    }
    from epsm_core import Footprint, GeometrySpec, scene_schema
    from epsm_viewer import write_scene
    from jsonschema import Draft202012Validator

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(12, 8), storeys=2, storey_height_m=3
    )
    scene = geometry.scene()
    serialized = json.dumps(scene, indent=2, allow_nan=False) + "\n"
    schema = scene_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(scene)
    with tempfile.TemporaryDirectory(prefix="epsm-viewer-handoff-") as temporary:
        directory = write_scene(scene, directory=Path(temporary) / "preview")
        if json.loads((directory / "model.json").read_text()) != scene:
            raise RuntimeError("Python Viewer changed the producer scene")
    if json.dumps(scene, indent=2, allow_nan=False) + "\n" != serialized:
        raise RuntimeError("Python Viewer mutated the producer scene")
    drawing = prepare_javascript_scene(
        scene,
        args.viewer_javascript_root,
        args.node,
        packages["epsm_viewer"]["version"],
    )
    scene_path = args.output.with_suffix(".scene.json")
    scene_path.write_text(serialized)
    return {
        "format": 1,
        "status": "passed",
        "packages": packages,
        "scene": {
            "schema": scene["schema"],
            "units": scene["units"],
            "up_axis": scene["up_axis"],
            "object_count": len(scene["objects"]),
            "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
            "path": str(scene_path),
            "inputs": "Synthetic 12 m by 8 m rectangle; two 3 m storeys; geometry only",
        },
        "python_viewer": "public write_scene retained the unchanged scene",
        "javascript_viewer": drawing,
        "scope": "Display handoff; no engine, browser, database or empirical accuracy claim",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "compatibility.json")
    parser.add_argument("--viewer-javascript-root", type=Path, required=True)
    parser.add_argument("--core-revision", required=True)
    parser.add_argument("--viewer-revision", required=True)
    parser.add_argument("--node", default="node")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        report = run_handoff(args)
    except Exception as error:
        report = {
            "format": 1,
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Viewer handoff {report['status']}: {args.output}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
