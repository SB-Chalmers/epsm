"""Common result boundary for both thermal engines.

The first harmonised delivery boundary is space heating plus ventilation fans.
DHW, cooling and plug loads remain separate thermal/electrical outputs and are
never silently included in that boundary. Whole-building assessment therefore
requires a separately implemented delivery boundary.
"""

import math

from .results import EnergyResult


def _input_identity(spec):
    """Identity of the resolved physical inputs supplied to an engine."""
    return {
        "physical_inputs_sha256": spec.physical_hash(),
        "weather_sha256": spec.climate.weather_sha256,
        "calendar_year": spec.climate.calendar_year,
    }


def _check_identity(diagnostics, expected):
    for field, value in expected.items():
        if field in diagnostics and diagnostics[field] != value:
            raise ValueError(
                f"Energy result {field} conflicts with captured simulation inputs"
            )


def cached_energy_matches(spec, energy, *, engine):
    """Require captured input identity before reusing a normalized calculation.

    Legacy entries without the evidence must be recomputed. Conflicting
    evidence is an error, never overwritten with the requested inputs.
    """
    if energy.get("engine") != engine:
        raise ValueError("Cached energy engine conflicts with requested engine")
    diagnostics = energy.get("diagnostics", {})
    expected = _input_identity(spec)
    _check_identity(diagnostics, expected)
    return all(field in diagnostics for field in expected)


def normalize_energy(spec, result, *, engine, state_id=None):
    """Bind engine output to its actual resolved inputs without inventing a run ID."""
    diagnostics = dict(result.diagnostics)
    captured = _input_identity(spec)
    if state_id is not None:
        captured["building_snapshot_id"] = state_id
    _check_identity(diagnostics, captured)
    diagnostics.update(captured)
    scalars = dict(result.scalars)
    requirements, carriers = [], {}
    delivery = spec.delivery.heating
    if delivery is None:
        requirements.append(
            "Explicit space-heating delivery and fan accounting are required"
        )
    else:
        carrier = {
            "electric_direct": "electricity",
            "heat_pump": "electricity",
            "district_heat": "district_heat",
            "fuel": "fuel",
        }[delivery.carrier]
        amount = scalars.get("space_heating_carrier_input_kwh")
        if amount is None or not math.isfinite(amount) or amount < 0:
            requirements.append("Space-heating carrier input is missing or invalid")
        else:
            carriers[carrier] = amount
        if spec.airflow.topology != "S":
            fan = scalars.get("ventilation_fan_electricity_kwh")
            if fan is None or not math.isfinite(fan) or fan < 0:
                requirements.append("Ventilation fan electricity is missing or invalid")
            else:
                carriers["electricity"] = carriers.get("electricity", 0) + fan
    time_axis = [] if result.time_axis is None else [str(x) for x in result.time_axis]
    return EnergyResult(
        engine=engine,
        scalars=scalars,
        hourly=result.hourly,
        units=result.units,
        diagnostics=diagnostics,
        artifacts=result.artifacts,
        delivered_by_carrier=carriers,
        requirements=requirements,
        time_axis=time_axis,
        annual=len(time_axis) == spec.climate.hours_in_year,
        run_id=result.run_id,
    )
