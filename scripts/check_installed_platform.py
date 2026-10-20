# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
"""Require offline record → Building → scene and RC → renovation LCA handoffs.

Database records and stock iteration use synthetic evidence; energy is a real
annual RC calculation. No live database, provider acquisition or cluster is used.
"""

import argparse
import importlib
import json
import sys
from dataclasses import replace
from datetime import date
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace


def check_model_scene(building):
    """Validate detached JSON polygons and physical identities without display."""
    from epsm_core import scene_schema
    from jsonschema import Draft202012Validator

    before = building.to_dict()
    imported = set(sys.modules)
    scene = json.loads(json.dumps(building.scene(), allow_nan=False))
    Draft202012Validator(scene_schema()).validate(scene)
    if not scene["objects"]:
        raise RuntimeError("Authored geometry produced an empty scene")
    if (
        scene["report"]["building_id"] != building.identifier
        or scene["report"]["snapshot_id"] != building.snapshot().sha256
    ):
        raise RuntimeError("Scene lost its physical Building identity")
    owners = {
        obj["metadata"]["physical_element_id"]
        for obj in scene["objects"]
        if "physical_element_id" in obj["metadata"]
    }
    if not owners or not owners <= {
        element.identifier for element in building.elements
    }:
        raise RuntimeError("Scene lost its physical element ownership")
    if building.to_dict() != before:
        raise RuntimeError("Scene export changed the physical Building")
    if any(
        name.split(".")[0] in {"epsm_viewer", "anywidget", "ipywidgets"}
        for name in set(sys.modules) - imported
    ):
        raise RuntimeError("Scene export imported display dependencies")
    return scene


def check_record_geometry(record, *, storeys, storey_height_m):
    """Require explicit geometry assumptions while retaining stored height evidence.

    Total component height evidence is portable source data. The current public
    record conversion needs an explicit model storey height; this check does not
    derive that assumption from the stored evidence or invent missing values.
    """
    from epsm_core import ProvenanceSpec, SourceRecord

    from epsm import Building

    original = json.loads(json.dumps(record.to_dict(), allow_nan=False))
    missing = replace(record, heights=())
    missing_portable = json.loads(json.dumps(missing.to_dict(), allow_nan=False))
    for portable in (original, missing_portable):
        draft = Building.from_record(portable, storeys=storeys)
        source = draft.to_dict()["source_record"]
        if (
            draft.geometry is not None
            or "storey_height_m" not in source["requirements"]
        ):
            raise RuntimeError("Record conversion silently completed a missing height")
        try:
            draft.readiness("geometry").require()
        except ValueError:
            pass
        else:
            raise RuntimeError("Geometry readiness accepted a missing height")
        if source["portable_record"] != portable:
            raise RuntimeError("Incomplete authoring changed portable evidence")
    provenance = ProvenanceSpec(
        records=(
            SourceRecord(
                field_path="geometry.parts",
                status="assumed",
                source="ASSUMED portable software fixture; not measured building geometry",
                assumption_profile="installed-record-geometry-fixture",
                evidence={"storeys": storeys, "storey_height_m": storey_height_m},
            ),
        )
    )
    for portable in (original, missing_portable):
        authored = Building.from_record(
            portable,
            storeys=storeys,
            storey_height_m=storey_height_m,
        )
        authored.provenance = provenance
        authored.readiness("geometry").require()
        if authored.to_dict()["source_record"]["portable_record"] != portable:
            raise RuntimeError("Explicit geometry assumptions changed height evidence")
        if authored.provenance.records != provenance.records:
            raise RuntimeError("Explicit geometry assumptions lost their provenance")
        scene = check_model_scene(authored)
    if json.loads(json.dumps(record.to_dict(), allow_nan=False)) != original:
        raise RuntimeError("Record authoring changed the supplied evidence")
    return {
        "missing_height_rejected": True,
        "explicit_height_geometry_ready": True,
        "stored_height_evidence_retained": True,
        "scene_schema": scene["schema"],
        "scene_objects": len(scene["objects"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--require-wheels", action="store_true")
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    installed = {}
    for name in (
        "epsm",
        "epsm_core",
        "epsm_data",
        "epsm_db",
        "epsm_rc",
        "epsm_lca",
        "epsm_studies",
        "smhi2epw",
    ):
        module = importlib.import_module(name)  # Required dependencies never skip.
        path = Path(module.__file__).resolve()
        if args.require_wheels and "site-packages" not in path.parts:
            raise RuntimeError(f"{name} imported outside the wheel environment: {path}")
        installed[name] = {"version": metadata.version(name), "import_path": str(path)}

    from epsm_db import BuildingRecord, BuildingType, Stock
    from epsm_studies import PaperStudy
    from sweden_ubem.stock import StockCell

    from epsm import Building, Evaluation, Weather, assess_renovation

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    from renovation_case import make_case, rc_settings

    case = make_case()
    template = case["baseline"]
    footprint = template.geometry.parts[0].footprint.polygon
    record = BuildingRecord(
        "synthetic-release",
        "shared-certificate-building",
        BuildingType("multi_family"),
        footprint,
        {"construction_year": 1960},
        components=({"component_id": "part", "geometry": footprint},),
        heights=(
            {
                "component_id": "part",
                "height_status": "determined",
                "representative_height_m": 8.4,
                "source": "synthetic-stored-height-release",
            },
        ),
        certificates=(
            {
                "certificate_id": "shared",
                "certificate_date": date(2025, 1, 1),
                "subject_count": 2,
                "loaded_building_count": 2,
            },
        ),
        subjects=(
            {"certificate_id": "shared", "building_id": "one"},
            {"certificate_id": "shared", "building_id": "two"},
        ),
        quality_findings=({"code": "synthetic-shared-certificate"},),
        _database_url="postgresql://never-retain-this-secret",
    )
    record_contract = check_record_geometry(record, storeys=3, storey_height_m=2.8)

    class FixtureCell(StockCell):
        def iter_records(self, *, batch_size=100):
            yield record

    cell = FixtureCell(
        Stock(SimpleNamespace(dataset_id="synthetic-release")), "multi_family", "SE.02"
    )
    physical = {
        key: getattr(template, key)
        for key in (
            "construction_set",
            "facade",
            "hvac",
            "operation",
            "foundation",
            "thermal_bridge_uplift_fraction",
            "load_reference_area_policy",
        )
    }
    models, receipts = cell.to_epsm(storeys=3, storey_height_m=2.8, **physical)
    if len(models) != 1 or len(receipts) != 1 or receipts[0].errors:
        raise RuntimeError("Stock conversion did not retain its model and receipt")
    baseline = models[0]
    scene = check_model_scene(baseline)
    (directory / "scene.json").write_text(json.dumps(scene, allow_nan=False) + "\n")
    baseline.assessment = case["settings"]
    states = [baseline]
    for measure in case["measures"]:
        states.append(states[-1].renovate(measure))
    from importlib.resources import files

    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
    runs = [
        building.simulate(
            engine="epsm_rc",
            weather=weather,
            settings=rc_settings(),
            directory=directory / f"step-{step}",
        )
        for step, building in enumerate(states)
    ]
    report = assess_renovation(
        states[-1],
        case["settings"],
        energy={i: run.annual_energy() for i, run in enumerate(runs)},
    )
    if not report.complete or not all(run.energy.complete for run in runs):
        raise RuntimeError("Annual energy or renovation assessment is incomplete")
    report_path = report.save(directory / "renovation.json")
    assert type(report).load(report_path) == report
    expected = json.loads(json.dumps(record.to_dict()))
    for step, (building, run) in enumerate(zip(states, runs)):
        payload = building.to_dict()
        assert "never-retain-this-secret" not in json.dumps(payload)
        restored = Building.from_dict(payload)
        assert restored.to_dict()["source_record"]["portable_record"] == expected
        saved = directory / f"step-{step}" / run.id / "evaluation.json"
        evaluation = Evaluation.from_dict(json.loads(saved.read_text()))
        evidence = evaluation.source_record["portable_record"]
        assert evidence == expected
        decoded = BuildingRecord.from_dict(evidence)
        assert decoded.certificates[0]["certificate_date"] == date(2025, 1, 1)
        assert decoded.atemp_m2 is None and len(decoded.subjects) == 2
    PaperStudy(
        name="offline-platform-contract",
        question="Do installed package handoffs preserve meaning?",
        configuration={"synthetic_evidence": True},
        sources={"record": expected},
    ).save(directory / "protocol.json")
    if any(name in sys.modules for name in ("epsm_viewer", "anywidget", "ipywidgets")):
        raise RuntimeError("Scientific handoffs imported display dependencies")
    result = {
        "packages": installed,
        "wheel_imports_required": args.require_wheels,
        "record_id": record.building_id,
        "record_geometry_contract": record_contract,
        "scene_schema": scene["schema"],
        "scene_objects": len(scene["objects"]),
        "states": len(states),
        "energy_kwh": [run.energy.annual_delivered_energy_kwh for run in runs],
        "assessment_complete": report.complete,
        "display_dependencies_used": False,
        "live_services_used": False,
    }
    (directory / "compatibility-report.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
