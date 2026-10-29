"""Scheduled-flow regression checks independent of optional record/database packages."""

from datetime import date, timedelta

import numpy as np
import pytest
from epsm_core import ScheduleSpec, resolve_operating_profile
from epsm_data import select_operating_profile

from epsm._programme_airflow import normal_use_airflow


@pytest.mark.parametrize(
    "category,expected_hours,design_flow",
    [
        ("office", 2700, 1.3),
        ("school", 2200, 3.0),
    ],
)
@pytest.mark.parametrize("year", [2023, 2024])
def test_source_outdoor_air_timetable_survives_natural_topology(
    category,
    expected_hours,
    design_flow,
    year,
):
    profile = select_operating_profile(category)
    day = date(year, 1, 1)
    dates = []
    while len(dates) < profile.values["reference_active_days"]:
        if day.weekday() < 5:
            dates.append(day.isoformat())
        day += timedelta(days=1)
    resolved = resolve_operating_profile(
        profile,
        calendar={
            "calendar_year": year,
            "active_dates": dates,
            "calendar_source": "Explicit test dates; no claim about actual term or holidays",
        },
    )
    source = resolved.assumptions["airflow"]
    fraction = ScheduleSpec.model_validate(source["mechanical_vent_fraction"])
    options = dict(
        infiltration={
            "envelope_infiltration_ach": 0.2,
            "infiltration_fraction": ScheduleSpec.constant(0.4),
        },
        flow_l_s_m2=source["mechanical_vent_l_s_m2"],
        fraction=fraction,
        reference_area_m2=90,
        conditioned_volume_m3=300,
        recovery_effectiveness=0.7,
    )
    natural = normal_use_airflow(ventilation="S", **options)
    mechanical = normal_use_airflow(ventilation="FTX", **options)
    natural_flow = (
        natural.natural_exchange_ach
        * 300
        / 3.6
        * np.asarray(natural.natural_exchange_fraction.hourly(year))
    )
    mechanical_flow = (
        mechanical.mechanical_vent_l_s_m2
        * 90
        * np.asarray(mechanical.mechanical_vent_fraction.hourly(year))
    )
    np.testing.assert_allclose(natural_flow, mechanical_flow, rtol=1e-14, atol=1e-12)
    assert natural_flow[0] == 0
    assert natural_flow.max() == pytest.approx(design_flow * 90)
    assert sum(natural.natural_exchange_fraction.hourly(year)) == expected_hours
    assert natural.mechanical_vent_l_s_m2 == 0
    assert natural.sensible_recovery_effectiveness == 0
    assert mechanical.sensible_recovery_effectiveness == 0.7
    assert natural.envelope_infiltration_ach == 0.2
    assert set(natural.infiltration_fraction.hourly(year)) == {0.4}
