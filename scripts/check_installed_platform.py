"""Require a complete offline DB → Building → RC → renovation LCA handoff.

Database records and stock iteration use synthetic evidence; energy is a real
annual RC calculation. No live database, provider acquisition or cluster is used.
"""

import argparse
import importlib
import json
import sys
from datetime import date
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace


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
        heights=({"component_id": "part", "height_m": 8.4},),
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
    result = {
        "packages": installed,
        "wheel_imports_required": args.require_wheels,
        "record_id": record.building_id,
        "states": len(states),
        "energy_kwh": [run.energy.annual_delivered_energy_kwh for run in runs],
        "assessment_complete": report.complete,
        "live_services_used": False,
    }
    (directory / "compatibility-report.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
