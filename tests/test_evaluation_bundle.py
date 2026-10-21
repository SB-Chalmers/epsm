"""Portable evaluations preserve raw identities and separate metadata from arrays."""

import json
import shutil

import numpy as np
import pytest

from epsm import Evaluation


def sample_evaluation(tmp_path):
    artifact = tmp_path / "engine.err"
    artifact.write_text("retained engine diagnostics")
    return Evaluation(
        id="evaluation-one",
        state_id="state",
        path_id="path",
        energy_id="energy",
        lca_id="lca",
        engine="epsm_rc",
        snapshot={"input": "evidence"},
        energy=dict(
            engine="epsm_rc",
            run_id="raw-engine-run",
            scalars={"heating": 3.0},
            hourly={"heating": [1.0, 2.0]},
            units={"heating": "kWh"},
            diagnostics={"accepted": True},
            artifacts={"errors": str(artifact)},
            delivered_by_carrier={},
            requirements=[],
            boundary="space_heating_and_fans",
            time_axis=["2023-01-01T00", "2023-01-01T01"],
            annual=False,
        ),
        lca={
            "status": "incomplete",
            "requirements": ["factors"],
            "material_gwp_kgco2e": None,
            "operational_gwp_kgco2e": None,
            "total_gwp_kgco2e": None,
        },
        diagnostics={},
    )


def test_bundle_is_relocatable_and_metadata_does_not_embed_arrays(tmp_path):
    original = sample_evaluation(tmp_path)
    destination = original.save_bundle(tmp_path / "saved")
    manifest = json.loads((destination / "manifest.json").read_text())
    metadata = json.loads((destination / "metadata.json").read_text())
    assert manifest["format"] == "epsm-evaluation-bundle/1"
    assert manifest["evaluation_id"] == original.id
    assert "hourly" not in metadata["energy"]
    assert "time_axis" not in metadata["energy"]
    assert metadata["energy"]["hourly_signals"] == ["heating"]
    assert metadata["energy"]["run_id"] == "raw-engine-run"
    moved = tmp_path / "relocated"
    shutil.move(destination, moved)
    (tmp_path / "engine.err").unlink()
    loaded = Evaluation.load_bundle(moved)
    assert loaded.energy.hourly == original.energy.hourly
    assert loaded.energy.time_axis == original.energy.time_axis
    assert loaded.energy.run_id == "raw-engine-run"
    assert loaded.lca.to_dict() == original.lca.to_dict()
    assert (
        moved / metadata["energy"]["artifacts"]["errors"]
    ).read_text() == "retained engine diagnostics"


def test_bundle_refuses_overwrite_and_detects_tampering(tmp_path):
    original = sample_evaluation(tmp_path)
    destination = original.save_bundle(tmp_path / "saved")
    with pytest.raises(FileExistsError):
        original.save_bundle(destination)
    manifest = json.loads((destination / "manifest.json").read_text())
    array = destination / manifest["arrays"]["hourly"]["heating"]["path"]
    np.save(array, np.array([9.0, 2.0]), allow_pickle=False)
    with pytest.raises(ValueError, match="checksum"):
        Evaluation.load_bundle(destination)


def test_bundle_rejects_paths_outside_bundle_even_with_matching_checksum(tmp_path):
    from epsm.io import load_bundle_metadata

    destination = sample_evaluation(tmp_path).save_bundle(tmp_path / "saved")
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["metadata"]["path"] = "../engine.err"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="relative|escape"):
        load_bundle_metadata(destination)


def test_bundle_metadata_checks_artifact_and_metadata_checksums(tmp_path):
    from epsm import load_bundle_metadata

    destination = sample_evaluation(tmp_path).save_bundle(tmp_path / "saved")
    manifest = json.loads((destination / "manifest.json").read_text())
    path = destination / manifest["artifacts"]["errors"]["path"]
    path.write_text("changed evidence")
    with pytest.raises(ValueError, match="checksum"):
        load_bundle_metadata(destination)
    path.write_text("retained engine diagnostics")
    (destination / "metadata.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        load_bundle_metadata(destination)


def test_bundle_reports_missing_optional_artifacts_and_preserves_old_energy(tmp_path):
    from epsm import EnergyResult, load_bundle_metadata

    original = sample_evaluation(tmp_path)
    (tmp_path / "engine.err").unlink()
    destination = original.save_bundle(tmp_path / "saved")
    metadata = load_bundle_metadata(destination)
    assert metadata["energy"]["diagnostics"]["unavailable_bundle_artifacts"] == [
        "errors"
    ]
    assert original.energy.artifacts
    legacy = original.energy.to_dict()
    legacy.pop("run_id")
    assert EnergyResult.from_dict(legacy).to_dict() == legacy


def test_normalization_keeps_raw_engine_run_identity():
    from types import SimpleNamespace

    from epsm.energy import normalize_energy

    spec = SimpleNamespace(
        delivery=SimpleNamespace(heating=None),
        climate=SimpleNamespace(
            hours_in_year=8760, weather_sha256="b" * 64, calendar_year=2023
        ),
        physical_hash=lambda: "a" * 64,
    )
    raw = SimpleNamespace(
        scalars={},
        hourly={},
        units={},
        diagnostics={},
        artifacts={},
        time_axis=None,
        run_id="engine-content-id",
    )
    assert normalize_energy(spec, raw, engine="epsm_rc").run_id == "engine-content-id"
