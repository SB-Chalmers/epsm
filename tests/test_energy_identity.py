"""Engine comparisons require identity captured at the actual simulation boundary."""

# Fixtures are shared with the public simulation tests.
# ruff: noqa: F811

from copy import deepcopy

import numpy as np
import pytest
from epsm_core.results import SimulationResult
from epsm_core.weather import hourly_axis
from test_platform import engine, reference, weather  # noqa: F401

from epsm import EvaluationCache, load_bundle_metadata
from epsm.energy import normalize_energy


@pytest.fixture
def controlled_runtime(monkeypatch):
    # The controlled engine fixture bypasses execution; avoid an unrelated
    # executable discovery requirement while preserving public simulate wiring.
    monkeypatch.setattr(
        "epsm.building.evaluation_identity",
        lambda **kwargs: {"energy": kwargs["engine"]},
    )


def raw_result(diagnostics=None):
    values = np.ones(8760)
    return SimulationResult(
        "actual-raw-run",
        {"space_heating_demand_kwh": 8760.0},
        {"space_heating_demand_kwh": values},
        {"space_heating_demand_kwh": "kWh"},
        {"accepted": True, **(diagnostics or {})},
        {},
        hourly_axis(2023),
    )


@pytest.mark.parametrize("engine_name", ["energyplus", "epsm_rc"])
def test_normalization_binds_actual_owner_spec_without_mutating_raw(
    weather, engine_name
):
    spec = reference().to_spec(weather)
    raw = raw_result()
    before = deepcopy(raw.diagnostics)
    normalized = normalize_energy(spec, raw, engine=engine_name)
    assert normalized.diagnostics["physical_inputs_sha256"] == spec.physical_hash()
    assert normalized.diagnostics["weather_sha256"] == weather.sha256
    assert normalized.diagnostics["calendar_year"] == weather.calendar_year
    assert normalized.run_id == "actual-raw-run"
    assert raw.diagnostics == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("physical_inputs_sha256", "a" * 64),
        ("weather_sha256", "b" * 64),
        ("calendar_year", 2022),
    ],
)
def test_conflicting_raw_identity_is_rejected(weather, field, value):
    with pytest.raises(ValueError, match=field):
        normalize_energy(
            reference().to_spec(weather),
            raw_result({field: value}),
            engine="energyplus",
        )


@pytest.mark.parametrize("engine_name", ["energyplus", "epsm_rc"])
def test_public_simulation_and_bundle_retain_actual_identity(
    tmp_path, weather, monkeypatch, engine_name, controlled_runtime
):
    module = __import__("epsm_core" if engine_name == "energyplus" else "epsm_rc")
    monkeypatch.setattr(
        module,
        "run_building" if engine_name == "energyplus" else "simulate_building",
        lambda *args, **kwargs: raw_result(),
    )
    building = reference()
    result = building.simulate(engine=engine_name, weather=weather, directory=tmp_path)
    diagnostics = result.energy.diagnostics
    assert (
        diagnostics["physical_inputs_sha256"]
        == building.to_spec(weather).physical_hash()
    )
    assert (
        diagnostics["building_snapshot_id"]
        == result.state_id
        == building.snapshot().sha256
    )
    assert (
        diagnostics["weather_sha256"]
        == result.weather["weather_sha256"]
        == weather.sha256
    )
    metadata = load_bundle_metadata(result.save_bundle(tmp_path / "bundle"))
    assert metadata["energy"]["diagnostics"] == diagnostics
    assert metadata["energy"]["run_id"] == "actual-raw-run"


@pytest.mark.parametrize(
    "missing", ["physical_inputs_sha256", "weather_sha256", "calendar_year"]
)
def test_legacy_cached_energy_without_identity_is_recomputed(
    tmp_path, weather, engine, missing
):
    building = reference()
    cache = EvaluationCache()
    first = building.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path
    )
    stale = first.energy.to_dict()
    stale["diagnostics"].pop(missing, None)
    cache.put("energy", first.energy_id, stale)
    second = building.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path
    )
    assert len(engine) == 2
    assert not second.diagnostics["energy_reused"]
    assert (
        second.energy.diagnostics["physical_inputs_sha256"]
        == building.to_spec(weather).physical_hash()
    )
    third = building.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path
    )
    assert third.diagnostics["energy_reused"]
    assert len(engine) == 2


def test_conflicting_cached_identity_is_not_relabelled(tmp_path, weather, engine):
    building = reference()
    cache = EvaluationCache()
    first = building.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path
    )
    stale = first.energy.to_dict()
    stale["diagnostics"]["physical_inputs_sha256"] = "a" * 64
    cache.put("energy", first.energy_id, stale)
    with pytest.raises(ValueError, match="physical_inputs_sha256"):
        building.simulate(
            engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path
        )
    assert len(engine) == 1


def test_conflicting_raw_snapshot_is_rejected(
    tmp_path, weather, monkeypatch, controlled_runtime
):
    import epsm_core

    monkeypatch.setattr(
        epsm_core,
        "run_building",
        lambda *args, **kwargs: raw_result({"building_snapshot_id": "wrong"}),
    )
    with pytest.raises(ValueError, match="building_snapshot_id"):
        reference().simulate(engine="energyplus", weather=weather, directory=tmp_path)
