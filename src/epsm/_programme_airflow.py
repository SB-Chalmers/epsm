"""Transfer normal-use outdoor-air rates without changing their timetable."""

from epsm_core import AirflowSpec, ScheduleSpec


def measured_air_change(profile, topology):
    """The measured total air change a profile gives this ventilation system, if any."""
    measured = profile.values.get("measured_use", {})
    return measured.get("ventilation", {}).get(topology, {}).get("total_air_change_ach")


def normal_use_airflow(
    *, ventilation, infiltration, flow_l_s_m2, fraction,
    reference_area_m2, conditioned_volume_m3, recovery_effectiveness,
):
    """Use the selected topology's scheduled equivalent flow.

    Natural exchange is a normal-use approximation, not pressure-driven airflow.
    The envelope infiltration definition and its independent schedule are retained.
    """
    natural = ventilation == "S"
    return AirflowSpec(
        topology=ventilation,
        **infiltration,
        natural_exchange_ach=(
            flow_l_s_m2 * reference_area_m2 * 3.6 / conditioned_volume_m3
            if natural else 0
        ),
        natural_exchange_fraction=fraction if natural else ScheduleSpec.constant(1),
        mechanical_vent_l_s_m2=0 if natural else flow_l_s_m2,
        mechanical_vent_fraction=fraction,
        sensible_recovery_effectiveness=(
            recovery_effectiveness if ventilation == "FTX" else 0
        ),
    )
