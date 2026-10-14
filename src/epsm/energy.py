"""Common result boundary for both thermal engines.

The first harmonised delivery boundary is space heating plus ventilation fans.
DHW, cooling and plug loads remain separate thermal/electrical outputs and are
never silently included in that boundary. Whole-building assessment therefore
requires a separately implemented delivery boundary.
"""

import math

from .results import EnergyResult


def normalize_energy(spec, result, *, engine):
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
        diagnostics=result.diagnostics,
        artifacts=result.artifacts,
        delivered_by_carrier=carriers,
        requirements=requirements,
        time_axis=time_axis,
        annual=len(time_axis) == spec.climate.hours_in_year,
    )
