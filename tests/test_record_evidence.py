"""Full portable evidence survives authoring and saved evaluations."""

# ruff: noqa: F811

import json
from datetime import date

import pytest
from shapely.geometry import Point, box
from test_platform import engine, reference, replacement, weather  # noqa: F401

from epsm import Building


@pytest.fixture
def source_record():
    db = pytest.importorskip("epsm_db")
    footprint = box(0, 0, 20, 12)
    return db.BuildingRecord(
        "evidence-release",
        "building-one",
        db.BuildingType("multi_family"),
        footprint,
        {"construction_year": 1960},
        components=({"component_id": "part-one", "geometry": footprint},),
        heights=({"component_id": "part-one", "height_m": 8.4, "source": "survey"},),
        purposes=({"purpose": "residential"},),
        addresses=({"geometry": Point(1, 2), "address_id": "address-one"},),
        properties=({"property_id": "property-one"},),
        certificates=(
            {
                "certificate_id": "shared",
                "certificate_date": date(2025, 1, 2),
                "subject_count": 2,
                "loaded_building_count": 2,
            },
        ),
        subjects=(
            {"certificate_id": "shared", "building_id": "building-one"},
            {"certificate_id": "shared", "building_id": "building-two"},
        ),
        observations=(
            {"certificate_id": "shared", "source_field": "area", "raw_values": ["900"]},
        ),
        epc_results=({"certificate_id": "shared", "temporal_status": "verified"},),
        quality_findings=({"code": "height_conflict", "source": "survey"},),
        _database_url="postgresql://private-secret",
    )


def authored_record(record):
    teaching = reference()
    options = {
        name: getattr(teaching, name)
        for name in (
            "construction_set",
            "facade",
            "hvac",
            "operation",
            "foundation",
            "thermal_bridge_uplift_fraction",
            "load_reference_area_policy",
        )
    }
    return Building.from_record(record, storeys=3, storey_height_m=2.8, **options)


def test_full_portable_evidence_survives_copy_serialization_and_renovation(
    source_record,
):
    expected = json.loads(json.dumps(source_record.to_dict()))
    building = authored_record(source_record)
    for candidate in (
        building,
        building.copy(),
        Building.from_dict(building.to_dict()),
        building.renovate(replacement(building)),
    ):
        saved = candidate.to_dict()["source_record"]
        assert saved["portable_record"] == expected
        assert "private-secret" not in json.dumps(saved)
        restored = type(source_record).from_dict(saved["portable_record"])
        assert restored.certificates[0]["certificate_date"] == date(2025, 1, 2)
        assert restored.components[0]["geometry"].equals(source_record.geometry)
        assert len(restored.subjects) == 2 and restored.atemp_m2 is None
    detached = building.to_dict()
    detached["source_record"]["portable_record"]["record"]["heights"].clear()
    assert building.to_dict()["source_record"]["portable_record"] == expected
    assert json.loads(json.dumps(source_record.to_dict())) == expected


def test_evaluation_keeps_complete_record_after_source_changes(
    source_record, weather, engine, tmp_path
):
    building = authored_record(source_record.to_dict())
    expected = json.loads(json.dumps(source_record.to_dict()))
    result = building.simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
    source_record.heights[0]["height_m"] = 99
    assert result.source_record["portable_record"] == expected
    saved = json.loads((tmp_path / result.id / "evaluation.json").read_text())
    assert saved["source_record"]["portable_record"] == expected


def test_old_summary_only_building_remains_readable(source_record):
    building = Building.from_record(source_record)
    old = building.to_dict()
    old["source_record"].pop("portable_record", None)
    restored = Building.from_dict(old)
    assert restored.to_dict()["source_record"] == old["source_record"]
    assert len(restored.compare()) == 2
