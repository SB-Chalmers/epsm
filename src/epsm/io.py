# File: src/epsm/io.py
# Purpose: Versioned portable evaluation bundles; no calculation or study policy.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# Date created: 2026-10-21
"""Explicit evaluation I/O with checksummed relative files and external arrays.

``metadata.json`` retains the evaluation's values and evidence, without hourly
arrays. ``manifest.json`` is the completion marker and documents every retained
file. NumPy is only needed when saving/loading arrays; reading metadata requires
the standard library alone within this module. No pickle or simulation is used.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import shutil
import tempfile
from pathlib import Path, PurePosixPath

FORMAT = "epsm-evaluation-bundle/1"
logger = logging.getLogger(__name__)


def _digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def _json(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate JSON field: {key}")
            value[key] = item
        return value

    def invalid(value):
        raise ValueError(f"Nonfinite JSON value: {value}")

    def finite(value):
        result = float(value)
        if not math.isfinite(result):
            invalid(value)
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=invalid,
        parse_float=finite,
    )


def _reference(root, relative):
    if not isinstance(relative, str):
        raise ValueError("Bundle references require relative paths")
    parts = PurePosixPath(relative)
    if (
        parts.is_absolute()
        or not parts.parts
        or any(p in {"..", "."} for p in parts.parts)
    ):
        raise ValueError(f"Bundle path must be relative and cannot escape: {relative}")
    path = root.joinpath(*parts.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Bundle path escapes directory: {relative}")
    if any(item.is_symlink() for item in (path, *path.parents) if item != root.parent):
        raise ValueError(f"Bundle references cannot use symbolic links: {relative}")
    if not path.is_file():
        raise ValueError(f"Missing bundle file: {relative}")
    return path


def _checked(root, reference, verify):
    if not isinstance(reference, dict) or not isinstance(reference.get("sha256"), str):
        raise ValueError("Bundle file reference requires path and sha256")
    path = _reference(root, reference.get("path"))
    if verify and _digest(path) != reference["sha256"]:
        raise ValueError(f"Bundle checksum mismatch: {reference['path']}")
    return path


def _manifest(root, verify=True):
    manifest = _json(_reference(root, "manifest.json"))
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ValueError("Unsupported evaluation bundle format")
    metadata = _json(_checked(root, manifest.get("metadata"), verify))
    if not isinstance(metadata, dict) or not isinstance(metadata.get("energy"), dict):
        raise ValueError("Bundle metadata requires evaluation and energy objects")
    if metadata.get("id") != manifest.get("evaluation_id"):
        raise ValueError("Bundle evaluation identity does not match metadata")
    arrays = manifest.get("arrays")
    if not isinstance(arrays, dict) or not isinstance(arrays.get("hourly"), dict):
        raise ValueError("Bundle manifest requires hourly array references")
    hourly = arrays["hourly"]
    if not isinstance(arrays.get("time_axis"), dict):
        raise ValueError("Bundle manifest requires a time-axis array reference")
    if set(hourly) != set(metadata.get("energy", {}).get("hourly_signals", [])):
        raise ValueError("Bundle hourly signal metadata does not match arrays")
    for reference in hourly.values():
        _checked(root, reference, verify)
    _checked(root, arrays["time_axis"], verify)
    if not isinstance(manifest.get("artifacts"), dict) or not isinstance(
        manifest.get("inputs", {}), dict
    ):
        raise ValueError("Bundle artifacts and inputs must be reference mappings")
    for reference in manifest.get("artifacts", {}).values():
        _checked(root, reference, verify)
    for reference in manifest.get("inputs", {}).values():
        _checked(root, reference, verify)
    for name, reference in manifest.get("artifacts", {}).items():
        if (
            metadata.get("energy", {}).get("artifacts", {}).get(name)
            != reference["path"]
        ):
            raise ValueError("Bundle artifact paths do not match metadata")
    weather = manifest.get("inputs", {}).get("weather")
    if weather is not None:
        if metadata.get("weather", {}).get("epw_path") != weather["path"]:
            raise ValueError("Bundle weather path does not match metadata")
        expected = metadata.get("weather", {}).get("weather_sha256")
        if expected is not None and expected != weather["sha256"]:
            raise ValueError("Bundle weather checksum does not match captured identity")
    return manifest, metadata


def load_bundle_metadata(directory, *, verify=True):
    """Read detached JSON metadata, optionally checking every retained file.

    Parameters
    ----------
    directory : str or pathlib.Path
        Completed evaluation bundle directory.
    verify : bool, default True
        Hash every referenced file when true. False still verifies path safety
        and file existence, but skips content hashes. No arrays are decoded.

    Returns
    -------
    dict
        Evaluation metadata with relative file references, signal names and all
        scalar values/units, diagnostics, LCA and calculation identities.

    Raises
    ------
    ValueError
        Unsupported format, unsafe paths, missing files or changed checksums.
    """
    return _manifest(Path(directory).resolve(), verify)[1]


def save_evaluation_bundle(evaluation, directory):
    """Write a new complete evaluation bundle; refuse existing destinations."""
    import numpy as np

    from .results import encode

    target = Path(directory).absolute()
    target.parent.mkdir(parents=True, exist_ok=True)
    metadata = evaluation.to_dict()
    energy = metadata["energy"]
    hourly, axis = energy.pop("hourly"), energy.pop("time_axis", [])
    energy["hourly_signals"] = list(hourly)
    manifest = dict(
        format=FORMAT,
        evaluation_id=metadata["id"],
        arrays={"hourly": {}},
        artifacts={},
        inputs={},
    )
    with tempfile.TemporaryDirectory(
        prefix=".epsm-bundle-", dir=target.parent
    ) as temporary:
        stage = Path(temporary)
        (stage / "arrays").mkdir()

        def reference(path):
            return {"path": path.relative_to(stage).as_posix(), "sha256": _digest(path)}

        def array(values, name, *, calendar=False):
            data = np.asarray(values, dtype=str if calendar else None)
            if data.ndim != 1 or data.dtype.kind not in ("US" if calendar else "biuf"):
                raise ValueError(
                    f"Bundle arrays must be one-dimensional numeric signals: {name}"
                )
            if not calendar and not np.isfinite(data).all():
                raise ValueError(f"Bundle arrays must be finite: {name}")
            path = stage / "arrays" / name
            np.save(path, data, allow_pickle=False)
            return {
                **reference(path),
                "dtype": str(data.dtype),
                "shape": list(data.shape),
            }

        for index, (name, values) in enumerate(hourly.items()):
            manifest["arrays"]["hourly"][name] = array(
                values, f"hourly-{index:04d}.npy"
            )
        manifest["arrays"]["time_axis"] = array(axis, "time-axis.npy", calendar=True)
        retained, unavailable = {}, []
        for index, (name, source) in enumerate(energy.get("artifacts", {}).items()):
            source = Path(source)
            if not source.is_file():
                unavailable.append(name)
                continue
            path = stage / "artifacts" / f"{index:04d}-{source.name}"
            path.parent.mkdir(exist_ok=True)
            shutil.copyfile(source, path)
            manifest["artifacts"][name] = reference(path)
            retained[name] = path.relative_to(stage).as_posix()
        energy["artifacts"] = retained
        if unavailable:
            energy.setdefault("diagnostics", {})["unavailable_bundle_artifacts"] = (
                unavailable
            )
        weather = metadata.get("weather", {})
        if weather.get("epw_path"):
            source = Path(weather["epw_path"])
            if not source.is_file():
                raise ValueError(f"Missing retained weather file: {source}")
            path = stage / "weather.epw"
            shutil.copyfile(source, path)
            manifest["inputs"]["weather"] = reference(path)
            expected = weather.get("weather_sha256")
            if (
                expected is not None
                and expected != manifest["inputs"]["weather"]["sha256"]
            ):
                raise ValueError("Weather checksum changed after evaluation")
            weather["epw_path"] = "weather.epw"
        path = stage / "metadata.json"
        path.write_text(encode(metadata), encoding="utf-8")
        manifest["metadata"] = reference(path)
        (stage / "manifest.json").write_text(encode(manifest), encoding="utf-8")
        # mkdir enforces no-overwrite even when another writer wins the race.
        target.mkdir()
        try:
            for path in stage.iterdir():
                if path.name != "manifest.json":
                    shutil.move(str(path), target / path.name)
            shutil.move(str(stage / "manifest.json"), target / "manifest.json")
        except Exception:
            shutil.rmtree(target)
            raise
    logger.info(
        "Saved evaluation bundle",
        extra={
            "epsm_event": "evaluation.bundle.saved",
            "epsm_details": {"evaluation_id": metadata["id"], "path": str(target)},
        },
    )
    return target.resolve()


def load_evaluation_bundle(directory):
    """Verify bundle files and restore the ordinary evaluation dictionary."""
    import numpy as np

    root = Path(directory).resolve()
    manifest, metadata = _manifest(root)

    def array(reference):
        value = np.load(_checked(root, reference, True), allow_pickle=False)
        if list(value.shape) != reference.get("shape") or str(
            value.dtype
        ) != reference.get("dtype"):
            raise ValueError(f"Bundle array description mismatch: {reference['path']}")
        if value.ndim != 1 or value.dtype.kind not in "biufUS":
            raise ValueError(f"Invalid bundle array: {reference['path']}")
        if value.dtype.kind in "biuf" and not np.isfinite(value).all():
            raise ValueError(f"Nonfinite bundle array: {reference['path']}")
        return value.tolist()

    energy = metadata["energy"]
    energy.pop("hourly_signals")
    energy["hourly"] = {
        name: array(ref) for name, ref in manifest["arrays"]["hourly"].items()
    }
    energy["time_axis"] = array(manifest["arrays"]["time_axis"])
    energy["artifacts"] = {
        name: str(_checked(root, ref, True))
        for name, ref in manifest["artifacts"].items()
    }
    if "weather" in manifest.get("inputs", {}):
        metadata["weather"]["epw_path"] = str(
            _checked(root, manifest["inputs"]["weather"], True)
        )
    return metadata
