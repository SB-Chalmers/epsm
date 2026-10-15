# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Require authored/catalogue wheel application, real RC and EnergyPlus 24.2.

The model uses explicit teaching geometry, systems, area and site assumptions.
This verifies package connections and retained evidence, not scientific accuracy.
Missing required prerequisites fail and are saved as failures, never skips.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
from importlib import metadata
from importlib.resources import files
from pathlib import Path

REQUIRED_PACKAGES = ("epsm", "epsm_core", "epsm_data", "epsm_rc", "epsm_lca")


def require_energyplus(path):
    """Return the actual executable version, or fail the required prerequisite."""
    executable = Path(path).resolve()
    if not executable.is_file():
        raise RuntimeError(f"EnergyPlus prerequisite missing: {executable}")
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RuntimeError(
            f"EnergyPlus prerequisite could not execute: {executable}"
        ) from error
    if "24.2" not in result.stdout:
        raise RuntimeError(
            f"EnergyPlus prerequisite requires 24.2: {result.stdout.strip()}"
        )
    return result.stdout.strip()


def read_receipt(path):
    """Require exact checked-out revisions instead of moving refs or missing evidence."""
    try:
        receipt = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(
            f"Required revision receipt is unavailable: {path}"
        ) from error
    packages = receipt.get("packages", {})
    if not set(REQUIRED_PACKAGES) <= set(packages) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("revision"), str)
        or re.fullmatch(r"[0-9a-f]{40}", row["revision"]) is None
        or not isinstance(row.get("version"), str)
        or not row["version"]
        for row in packages.values()
    ):
        raise RuntimeError(
            "Required package receipt must record exact revisions and versions"
        )
    return receipt


def installed_packages(receipt, *, require_wheels):
    """Check actual imports and versions against the retained producer receipt."""
    observed = {}
    for name, evidence in receipt["packages"].items():
        module = importlib.import_module(name)
        imported = Path(module.__file__).resolve()
        version = metadata.version(name)
        direct = metadata.distribution(name).read_text("direct_url.json")
        editable = bool(
            direct and json.loads(direct).get("dir_info", {}).get("editable")
        )
        if require_wheels and ("site-packages" not in imported.parts or editable):
            raise RuntimeError(f"Installed wheel required for {name}: {imported}")
        if version != evidence["version"]:
            raise RuntimeError(
                f"Installed version differs from revision receipt: {name} {version}"
            )
        observed[name] = {
            **evidence,
            "import_path": str(imported),
            "editable": editable,
        }
    return observed


def sha256(path):
    """Hash a retained input or wheel without loading the entire artifact in memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run_cases(directory, energyplus):
    """Apply both definitions to existing geometry and execute real engine handoffs."""
    from epsm_data import (
        Archetype,
        Catalogue,
        HVACTemplate,
        OperatingProfile,
        archetype_from_dict,
        archetype_to_dict,
    )

    from epsm import Building, Weather

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    from renovation_case import make_case, rc_settings

    reference = make_case()["baseline"]
    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
    systems = HVACTemplate(
        "installed:chosen-systems",
        reference.hvac.to_dict(),
        ("ASSUMED teaching HVAC; explicitly selected for this software check",),
    )
    catalogue = (
        Catalogue.load()
        .get("mf_se02", state="existing")
        .with_changes(hvac_template=systems)
    )
    custom = Archetype(
        "installed:authored",
        "Authored software-check definition",
        construction_set=catalogue.construction_set,
        operating_profile=OperatingProfile(
            "installed:explicit-use",
            {
                "building_assumptions": {
                    "use": reference.operation.model_dump(mode="json")
                }
            },
            ("ASSUMED existing teaching operation; explicitly selected",),
        ),
        hvac_template=systems,
        source_references=(
            "Software integration fixture, not observed building evidence",
        ),
    )
    output = []
    for label, definition in (("catalogue", catalogue), ("authored", custom)):
        payload = archetype_to_dict(definition)
        assert payload["format_version"] == 4
        restored = archetype_from_dict(json.loads(json.dumps(payload)))
        assert restored == definition
        (directory / f"{label}-archetype.json").write_text(
            json.dumps(payload, indent=2) + "\n"
        )
        building = Building.from_dict(reference.to_dict())
        # Existing geometry and explicit site/bridge choices remain the test basis.
        building.elements = tuple(
            e.with_changes(construction=None) for e in building.elements
        )
        building.operation = None
        building.hvac = None
        building.load_reference_area_policy = None
        building.load_reference_area_m2 = (
            720  # Explicit synthetic Atemp assertion, 3 x 20 x 12 m².
        )
        before = building.snapshot().to_dict()
        calendar = {"calendar_year": 2023} if label == "catalogue" else None
        report = building.apply_archetype(restored, calendar=calendar)
        if report.requirements:
            raise RuntimeError(f"{label} remains unresolved: {report.requirements}")
        after = building.snapshot().to_dict()
        for field in (
            "geometry",
            "context",
            "foundation",
            "ground_temperature",
        ):
            assert after[field] == before[field]
        for key in before["facade"]:
            if key not in {"solar_shading_factor", "glazing"}:
                assert after["facade"][key] == before["facade"][key]
        assert [(e["identifier"], e["area_m2"]) for e in after["elements"]] == [
            (e["identifier"], e["area_m2"]) for e in before["elements"]
        ]
        portable = Building.from_dict(json.loads(json.dumps(building.to_dict())))
        assert portable.archetype_applications[-1].to_dict() == report.to_dict()
        engines = ("epsm_rc", "energyplus") if label == "catalogue" else ("epsm_rc",)
        evaluations = []
        for engine in engines:
            options = (
                {"settings": rc_settings()}
                if engine == "epsm_rc"
                else {"energyplus": energyplus}
            )
            evaluation = portable.simulate(
                engine=engine,
                weather=weather,
                directory=directory / label / engine,
                **options,
            )
            if (
                not evaluation.energy.complete
                or evaluation.energy.annual_delivered_energy_kwh <= 0
            ):
                raise RuntimeError(
                    f"{label}/{engine} did not produce accepted annual energy"
                )
            assert evaluation.archetype_applications[-1] == report.to_dict()
            evaluations.append(
                {
                    "engine": engine,
                    "id": evaluation.id,
                    "annual_delivered_energy_kwh": evaluation.energy.annual_delivered_energy_kwh,
                    "requirements": list(evaluation.energy.requirements),
                }
            )
        output.append(
            {
                "route": label,
                "application": report.to_dict(),
                "evaluations": evaluations,
            }
        )
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--energyplus-exe", type=Path, required=True)
    parser.add_argument("--compatibility-receipt", type=Path, required=True)
    parser.add_argument(
        "--wheels", type=Path, help="Directory of actual installed build artifacts"
    )
    parser.add_argument("--require-wheels", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    evidence = {
        "format": 1,
        "status": "failed",
        "synthetic_inputs": True,
        "live_services_used": False,
        "wheel_imports_required": args.require_wheels,
    }
    try:
        evidence["energyplus_version"] = require_energyplus(args.energyplus_exe)
        evidence["compatibility_receipt"] = read_receipt(args.compatibility_receipt)
        evidence["packages"] = installed_packages(
            evidence["compatibility_receipt"], require_wheels=args.require_wheels
        )
        if args.require_wheels and args.wheels is None:
            raise RuntimeError(
                "Installed checks require the actual built wheel directory"
            )
        if args.wheels is not None:
            wheels = sorted(args.wheels.glob("*.whl"))
            if not wheels:
                raise RuntimeError("No built wheel artifacts supplied")
            evidence["wheels"] = {wheel.name: sha256(wheel) for wheel in wheels}
        evidence["cases"] = run_cases(directory, str(args.energyplus_exe.resolve()))
        evidence["status"] = "passed"
    except Exception as error:
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (directory / "archetype-compatibility-report.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
    print(
        f"Passed installed authored/catalogue application, RC and EnergyPlus: {directory}"
    )


if __name__ == "__main__":
    main()
