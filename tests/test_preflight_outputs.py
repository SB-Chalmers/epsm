"""Study-facing validation distinguishes thermal, delivery and LCA completeness."""

from importlib.resources import files

import numpy as np
import pytest
from epsm_core.weather import hourly_axis

from epsm import Building, Evaluation, Weather


def evaluated(*, delivery=True, lca=False):
    values = np.ones(8760)
    return Evaluation(
        id="evaluation",
        weather={"calendar_year": 2023},
        energy={
            "engine": "epsm_rc",
            "scalars": {"space_heating_demand_kwh": 8760},
            "hourly": {"space_heating_demand_kwh": values},
            "time_axis": hourly_axis(2023).astype(str).tolist(),
            "units": {"space_heating_demand_kwh": "kWh"},
            "annual": True,
            "requirements": [] if delivery else ["Missing carrier accounting"],
            "diagnostics": {"accepted": True},
            "delivered_by_carrier": {"electricity": 8760} if delivery else {},
        },
        lca={
            "status": "complete" if lca else "incomplete",
            "requirements": [] if lca else ["factors"],
        },
    )


def test_output_validation_keeps_delivery_and_lca_separate():
    from epsm import validate_outputs

    result = validate_outputs(evaluated())
    assert (
        result["ready"] and result["thermal_complete"] and result["delivery_complete"]
    )
    assert not result["lca_complete"]
    result = validate_outputs(
        evaluated(), [{"name": "lca", "resolution": "assessment", "required": True}]
    )
    assert not result["ready"]
    assert result["thermal_complete"] and result["delivery_complete"]
    assert any(item["code"] == "lca_incomplete" for item in result["diagnostics"])
    result = validate_outputs(evaluated(delivery=False), ["space_heating_demand_kwh"])
    assert result["ready"] and not result["delivery_complete"]


@pytest.mark.parametrize("damage", ["calendar", "annual", "units", "nonfinite"])
def test_thermal_outputs_must_match_calendar_units_and_annual_totals(damage):
    from epsm import validate_outputs

    data = evaluated().to_dict()
    if damage == "calendar":
        data["energy"]["time_axis"][1] = data["energy"]["time_axis"][0]
    elif damage == "annual":
        data["energy"]["scalars"]["space_heating_demand_kwh"] = 100
    elif damage == "units":
        data["energy"]["units"]["space_heating_demand_kwh"] = "J"
    else:
        data["energy"]["hourly"]["space_heating_demand_kwh"][0] = float("nan")
    report = validate_outputs(data, ["space_heating_demand_kwh"])
    assert not report["ready"] and not report["thermal_complete"]


def test_epsm_preflight_uses_owner_policies_without_simulation(monkeypatch):
    from epsm_rc import RCSettings, platform

    from epsm import preflight

    monkeypatch.setattr(
        platform, "Building5R1C", lambda *args, **kwargs: pytest.fail("solver")
    )
    building = Building(preset="illustrative-reference")
    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
    report = preflight(
        building, weather=weather, engine="epsm_rc", settings=RCSettings()
    )
    assert not report["ready"]
    assert any(item["code"] == "rc_ground" for item in report["diagnostics"])


def test_optional_missing_signal_is_warning_and_zone_aggregate_does_not_match():
    from epsm import validate_outputs

    report = validate_outputs(evaluated(), [{"name": "missing", "required": False}])
    assert report["ready"]
    assert report["diagnostics"][0]["severity"] == "warning"
    report = validate_outputs(
        evaluated(), [{"name": "space_heating_demand_kwh", "level": "zone"}]
    )
    assert not report["ready"]
    assert any(item["code"] == "output_level" for item in report["diagnostics"])


def test_explicit_energyplus_executable_is_checked_through_core(monkeypatch):
    import epsm_core

    from epsm import preflight

    checked = []
    monkeypatch.setattr(
        epsm_core,
        "EnergyPlusCompiler",
        lambda executable, **kwargs: checked.append(executable),
    )
    preflight(
        Building(), engine="energyplus", energyplus="/selected/EnergyPlus", outputs=[]
    )
    assert checked == ["/selected/EnergyPlus"]
