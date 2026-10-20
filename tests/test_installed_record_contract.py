# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
"""The installed gate rejects implicit heights and exports portable scenes."""

import importlib.util
from pathlib import Path

import pytest
from shapely.geometry import box

db = pytest.importorskip("epsm_db")

SPEC = importlib.util.spec_from_file_location(
    "installed_platform_gate",
    Path(__file__).resolve().parents[1] / "scripts/check_installed_platform.py",
)
GATE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATE)


@pytest.fixture
def record():
    return db.BuildingRecord(
        "synthetic-release",
        "portable-building",
        db.BuildingType("multi_family"),
        box(0, 0, 12, 8),
        {},
        heights=(
            {
                "component_id": "part",
                "height_status": "determined",
                "representative_height_m": 8.4,
                "source": "synthetic-stored-height-release",
            },
        ),
        _database_url="postgresql://never-retain-this-secret",
    )


def test_portable_height_gate_preserves_evidence_and_explicit_assumptions(record):
    report = GATE.check_record_geometry(record, storeys=3, storey_height_m=2.8)
    assert report["missing_height_rejected"]
    assert report["explicit_height_geometry_ready"]
    assert report["stored_height_evidence_retained"]
    assert report["scene_schema"] == "epsm.scene/1"
    assert report["scene_objects"] > 0


def test_height_gate_detects_silent_default_height_regression(record, monkeypatch):
    from epsm import Building

    original = Building.from_record

    def silently_complete(cls, source, **options):
        options.setdefault("storey_height_m", 2.8)
        return original(source, **options)

    monkeypatch.setattr(Building, "from_record", classmethod(silently_complete))
    with pytest.raises(RuntimeError, match="missing height"):
        GATE.check_record_geometry(record, storeys=3, storey_height_m=2.8)


def test_scene_gate_needs_no_database_engine_or_display(record, monkeypatch):
    import builtins

    import epsm_core
    import psycopg

    from epsm import Building

    building = Building.from_record(record.to_dict(), storeys=3, storey_height_m=2.8)
    expected = building.to_dict()
    original = builtins.__import__

    def no_display(name, *args, **kwargs):
        if name.split(".")[0] in {"epsm_viewer", "anywidget", "ipywidgets"}:
            raise AssertionError("Scene export must not import display packages")
        return original(name, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Scene export must not open a database or engine")

    monkeypatch.setattr(builtins, "__import__", no_display)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(epsm_core, "EnergyPlusCompiler", forbidden)
    scene = GATE.check_model_scene(building)
    assert scene["report"]["building_id"] == building.identifier
    assert scene["report"]["source_crs"] == "EPSG:3006"
    assert building.to_dict() == expected


def test_scene_gate_rejects_invalid_transport_contract(record, monkeypatch):
    from jsonschema import ValidationError

    from epsm import Building

    building = Building.from_record(record.to_dict(), storeys=3, storey_height_m=2.8)
    invalid = building.scene()
    invalid["units"] = "ft"
    monkeypatch.setattr(Building, "scene", lambda self: invalid)
    with pytest.raises(ValidationError):
        GATE.check_model_scene(building)
