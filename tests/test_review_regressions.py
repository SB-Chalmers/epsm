"""Cross-package review regressions for evidence and retained calculations."""

# ruff: noqa: F811
import json
import shutil
from pathlib import Path

import pytest
from test_platform import engine, reference, weather  # noqa: F401

from epsm import Building, EvaluationCache
from epsm.results import EnergyResult, Evaluation


def test_portable_record_and_explicit_override_keep_source_evidence():
    from datetime import date

    from shapely.geometry import box

    db = pytest.importorskip("epsm_db")
    from sweden_ubem.enums import BuildingType

    record = db.BuildingRecord(
        "source",
        "record-1",
        BuildingType.RESIDENTIAL_MULTIFAMILY,
        box(0, 0, 20, 12),
        {"storey_height_m": 2.8},
        certificates=(
            {
                "certificate_id": "cert",
                "certificate_date": date(2024, 1, 1),
                "date_status": "verified",
                "subject_count": 1,
                "loaded_building_count": 1,
                "matching_status": "fully_matched",
            },
        ),
        observations=(
            {
                "certificate_id": "cert",
                "source_field": "EgenAntalPlan",
                "raw_values": ["2"],
                "mapping_status": "verified",
            },
        ),
    )
    b = Building.from_record(record.to_dict(), storeys=3)
    assert b.identifier == "record-1" and b.geometry is not None
    row = next(r for r in b.compare() if r["property"] == "storeys")
    assert (row["model"], row["observed"], row["difference"]) == (3, 2, 1)
    unmodified = Building.from_record(record.to_dict())
    assert unmodified.geometry is not None
    assert unmodified.compare()[1]["model"] == 2
    invalid = record.to_dict()
    invalid["crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="EPSG:3006"):
        Building.from_record(invalid)


def test_results_cannot_be_reassigned_and_evaluations_keep_separate_files(
    tmp_path, weather, engine
):
    b = reference()
    a = b.simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
    first = (tmp_path / a.id / "evaluation.json").read_bytes()
    c = b.simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
    assert a.id != c.id and c.diagnostics["energy_reused"]
    assert (tmp_path / a.id / "evaluation.json").read_bytes() == first
    assert (tmp_path / c.id / "evaluation.json").is_file()
    assert Path(a.weather["epw_path"]) != Path(c.weather["epw_path"])
    for obj, field in ((a, "id"), (a.energy, "engine"), (b, "results")):
        with pytest.raises(AttributeError):
            setattr(obj, field, "changed")
    assert Evaluation.__doc__ and EnergyResult.__doc__
    assert a.summary()["energy"]["complete"]


def test_disk_cache_is_relocatable_and_detects_changed_outputs(tmp_path):
    artifact = tmp_path / "original.csv"
    artifact.write_text("retained calculation")
    cache = EvaluationCache(tmp_path / "cache")
    cache.put(
        "energy",
        "key",
        dict(artifacts={"hourly": str(artifact)}, scalars={"energy": 10}),
    )
    artifact.unlink()
    shutil.move(tmp_path / "cache", tmp_path / "moved")
    moved = EvaluationCache(tmp_path / "moved")
    assert (
        Path(moved.get("energy", "key")["artifacts"]["hourly"]).read_text()
        == "retained calculation"
    )
    path = tmp_path / "moved/energy/key.json"
    data = json.loads(path.read_text())
    data["value"]["scalars"]["energy"] = 0
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Changed cache calculation"):
        moved.get("energy", "key")


def test_memory_cache_does_not_expose_missing_artifact_paths(tmp_path):
    from epsm.cache import materialize_artifacts

    result = materialize_artifacts(
        dict(artifacts={"hourly": str(tmp_path / "missing")}), tmp_path / "new"
    )
    assert result["artifacts"] == {}
    assert result["diagnostics"]["unavailable_cached_artifacts"] == ["hourly"]
