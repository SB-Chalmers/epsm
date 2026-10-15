from dataclasses import replace
from importlib.resources import files

import numpy as np
import pytest
from epsm_core import HVACSystem
from epsm_core.results import SimulationResult
from epsm_core.specs import DeliverySpec, HeatingDeliverySpec
from epsm_core.weather import hourly_axis
from epsm_data import ConstructionOperation, RenovationMeasure
from epsm_data.domain import BuildingElement as Role

from epsm import (
    AssessmentSettings,
    Building,
    EnvironmentalFactor,
    EvaluationCache,
    Weather,
)


@pytest.fixture
def weather():
    return Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")


def reference():
    building = Building(preset="illustrative-reference")
    building.hvac = HVACSystem(
        building.hvac.airflow,
        DeliverySpec(
            heating=HeatingDeliverySpec(
                carrier="district_heat",
                efficiency=0.95,
                specific_fan_power_w_per_l_s=1.5,
                source="Illustrative test input",
            )
        ),
    )
    return building


def assessment(building):
    factors = {}
    for row in building.quantities():
        factors[row.material_id] = {
            "A1A3": EnvironmentalFactor(
                1,
                "kg" if row.mass_kg is not None else "m2",
                "A1A3",
                "Synthetic test factor",
            )
        }
    return AssessmentSettings(
        30,
        "space_heating_and_fans",
        "retained",
        ("A1A3",),
        factors,
        {
            c: EnvironmentalFactor(0.1, "kWh", "B6", "Synthetic test factor")
            for c in ("district_heat", "electricity")
        },
    )


def replacement(building, name="window"):
    window = building.construction_set.elements[Role.WINDOW]
    return RenovationMeasure(
        name,
        "envelope",
        name,
        "Like-for-like test replacement",
        "window",
        operations=(
            ConstructionOperation("replace_element", Role.WINDOW, element=window),
        ),
    )


@pytest.fixture
def engine(monkeypatch):
    calls = []

    def run(building, *, weather, directory=None, **options):
        calls.append(building.snapshot().sha256)
        hourly = dict(
            space_heating_demand_kwh=np.ones(8760),
            space_heating_carrier_input_kwh=np.ones(8760),
            ventilation_fan_electricity_kwh=np.full(8760, 0.1),
        )
        return SimulationResult(
            "test",
            {k: float(v.sum()) for k, v in hourly.items()},
            hourly,
            {k: "kWh" for k in hourly},
            {"accepted": True},
            {},
            hourly_axis(2023),
        )

    import epsm_rc

    monkeypatch.setattr(epsm_rc, "simulate_building", run)
    return calls


def test_results_are_stable_snapshots_and_lca_failure_preserves_energy(
    tmp_path, weather, engine, monkeypatch
):
    b = reference()
    assert b.results.latest is None
    a = b.simulate(engine="epsm_rc", weather=weather, directory=tmp_path / "one")
    assert a.lca.status == "incomplete"
    assert a.energy.annual_delivered_energy_kwh > 0
    from epsm import building as module

    def fail(*args, **kwargs):
        raise RuntimeError("test assessment failure")

    monkeypatch.setattr(module, "assess", fail)
    second = b.simulate(engine="epsm_rc", weather=weather, directory=tmp_path / "two")
    assert second.lca.status == "failed" and second.energy.complete
    assert second.annual_energy().state_id == second.state_id
    assert len(b.results) == 2
    data = a.energy.hourly
    data["space_heating_demand_kwh"][0] = -10
    assert a.energy.hourly["space_heating_demand_kwh"][0] == 1
    b.operation = b.operation.updated(equipment_gain_w_m2=10)
    assert not a.matches(b)


def test_path_inventory_survives_serialization_and_energy_reuses(
    tmp_path, weather, engine
):
    b = reference()
    b.assessment = assessment(b)
    one = b.renovate(replacement(b))
    two = one.renovate(replacement(one, "second-window"))
    assert isinstance(one, Building) and not one.results
    restored = Building.from_dict(two.to_dict())
    assert len(restored.material_flows) == 2
    cache = EvaluationCache(tmp_path / "cache")
    a = one.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path / "one"
    )
    c = restored.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path / "two"
    )
    assert a.energy_id == c.energy_id
    assert a.lca_id != c.lca_id
    assert c.lca.material_gwp_kgco2e == pytest.approx(2 * a.lca.material_gwp_kgco2e)
    assert len(engine) == 1
    restored.assessment = replace(restored.assessment, period_years=60)
    d = restored.simulate(
        engine="epsm_rc", weather=weather, cache=cache, directory=tmp_path / "three"
    )
    assert d.energy_id == c.energy_id and d.lca_id != c.lca_id
    assert len(engine) == 1


def test_record_is_gradual_and_comparison_preserves_missing():
    b = Building.from_record({"building_id": "record", "facts": {}, "geometry": None})
    assert not b.readiness("geometry")
    assert all(r["difference"] is None for r in b.compare())


def test_real_rc_repeat_runs_are_independent(tmp_path, weather):
    from epsm_rc import RCSettings

    settings = RCSettings.from_policy(
        "epsm_rc_5r1c_v1",
        airflow_policy="sensible_only_unlimited_supply",
        ground_policy="conductance_multiplier",
    )
    b = reference()
    b.assessment = assessment(b)
    a = b.simulate(
        engine="epsm_rc", weather=weather, settings=settings, directory=tmp_path / "one"
    )
    c = b.simulate(
        engine="epsm_rc", weather=weather, settings=settings, directory=tmp_path / "two"
    )
    assert a.energy.complete and a.lca.complete
    assert a.energy.annual_delivered_energy_kwh > 0
    assert a.energy.scalars == c.energy.scalars
    assert a.energy.boundary == "space_heating_and_fans"
