"""Frozen LoD2 construction handover; Core dependencies are imported lazily."""
from __future__ import annotations

import math
from copy import deepcopy

from epsm_data import Catalogue, export_nominal_constructions

from epsm._logging import call_with_context


def _catalogue_view(catalogue=None, detailed=None):
    """Use the one frozen LoD2 catalogue; legacy inspection objects are retired."""
    if detailed is not None:
        raise TypeError("detailed is retired; pass a LoD2 Catalogue as catalogue")
    if catalogue is None:
        return call_with_context(Catalogue.load)
    if not isinstance(catalogue, Catalogue):
        raise TypeError("catalogue must be a LoD2 Catalogue")
    return catalogue


def _weather_shell(library, metadata, supplied):
    """Retain the declared representative shell until a caller supplies a roof."""
    from epsm_core.specs import ConstructionSpec

    if supplied is not None:
        return (supplied if isinstance(supplied, ConstructionSpec)
                else ConstructionSpec(**supplied)), "Caller-supplied weather-shell construction."
    if metadata.get("weather_shell") is not None:
        return ConstructionSpec(**metadata["weather_shell"]), (
            "Recorded representative weather shell; verify against the actual roof."
        )
    raise ValueError(
        "No recorded representative weather shell; supply an explicit weather_shell construction"
    )


def core_inputs(archetype_id, state=None, *, detailed=None, catalogue=None,
                basement_wall=None, weather_shell=None, ventilation=None):
    """Return native Core constructions from the frozen physical catalogue.

    The caller supplies geometry, weather, use, HVAC and ground boundaries.
    Cold-attic ventilation remains an explicit building input. The default
    weather shell is the recorded representative assumption, independently of
    the insulated ceiling; override it with a supplied ConstructionSpec.
    ``ventilation`` (S, F, FT or FTX) is the building's observed system; it
    selects only the archetype's airflow-only ventilation template.
    """
    from epsm_core.specs import ConstructionSpec, EnvelopeSpec, GlazingSpec

    library = _catalogue_view(catalogue, detailed)
    # Catalogue selection resolves legacy aliases and the explicit generic/MF
    # assumption without inserting another authored construction family.
    # An observed ventilation system selects the archetype's airflow template;
    # without one, Data applies the era default. Constructions do not change.
    archetype = call_with_context(library.get, archetype_id, state=state,
                                  ventilation=ventilation)
    metadata = library.nominal_metadata(archetype_id, state=state)
    bundle = export_nominal_constructions(archetype, metadata=metadata)
    core = bundle["core"]
    required = {"EXT_WALL", "GROUND_FLOOR", "INTERMEDIATE_FLOOR", "WINDOW"}
    missing = sorted(required - core.keys())
    if "TOP_FLOOR" not in core and "ROOF" not in core:
        missing.append("TOP_FLOOR or ROOF")
    if missing:
        raise ValueError("Core handover is missing physical roles: " + ", ".join(missing))
    roof = metadata.get("roof_topology")
    if roof not in {"cold_attic", "compact"}:
        raise ValueError("Core handover requires a declared roof_topology")
    shell, shell_note = _weather_shell(library, metadata, weather_shell)
    top = ConstructionSpec(**core.get("TOP_FLOOR", core.get("ROOF")))
    if "BASEMENT_WALL" in core:
        basement_wall = ConstructionSpec(**core["BASEMENT_WALL"])
    elif basement_wall is None:
        raise ValueError(
            "No basement-wall recipe: supply an explicit basement_wall construction; "
            "no floor substitution is made."
        )
    elif not isinstance(basement_wall, ConstructionSpec):
        basement_wall = ConstructionSpec(**basement_wall)
    envelope = EnvelopeSpec(
        wall=ConstructionSpec(**core["EXT_WALL"]), top=top,
        ground=ConstructionSpec(**core.get("BASEMENT_FLOOR", core["GROUND_FLOOR"])),
        basement_ceiling=(ConstructionSpec(**core["GROUND_FLOOR"])
                          if "BASEMENT_FLOOR" in core else None),
        intermediate_floor=ConstructionSpec(**core["INTERMEDIATE_FLOOR"]),
        weather_shell=shell, basement_wall=basement_wall,
    )
    return {
        "archetype": archetype, "envelope": envelope,
        "glazing": GlazingSpec(**core["WINDOW"]), "roof_topology": roof,
        "nominal_bundle": bundle,
        **({"selection": deepcopy(metadata["selection"])} if "selection" in metadata else {}),
        "requirements": {
            "attic_outdoor_air_ach": "required explicit assumption"
            if roof == "cold_attic" else "not applicable",
            "weather_shell": shell_note,
            "ground_temperature": "Caller must supply a ground boundary appropriate to the building.",
            "basement": "Geometry determines presence; no floor substitution is supplied.",
        },
    }


def apply_attic_ventilation(epjson, *, outdoor_air_ach):
    """Add an explicit constant outdoor-air exchange to unconditioned attic zones.

    Legacy Core creates attic geometry without unconditioned airflow. Current Core
    accepts UnconditionedExchangeSpec natively (3 October 2026); prefer that input
    so the exchange participates in compilation hashes and run provenance.
    The rate is a caller-owned scenario assumption, not a calibrated national value.
    Input is never mutated; duplicate application is rejected.
    """
    if isinstance(outdoor_air_ach, bool) or not math.isfinite(outdoor_air_ach) or outdoor_air_ach < 0:
        raise ValueError('Attic outdoor-air rate must be finite and nonnegative')
    model = deepcopy(epjson)
    zones = [name for name, z in model.get('Zone', {}).items()
             if 'attic' in name.lower() and z.get('part_of_total_floor_area') == 'No']
    if not zones:
        raise ValueError('No unconditioned attic zone found')
    # Prevent double counting if a caller combines the legacy adapter with native
    # Core exchange. Both are outdoor exchange scenarios, not leakage calibration.
    if any(item.get('zone_or_zonelist_or_space_or_spacelist_name') in zones
           for item in model.get('ZoneInfiltration:DesignFlowRate', {}).values()):
        raise ValueError('Attic ventilation already assigned')
    schedule = 'EPSM_v1_attic_exchange'
    if schedule in model.get('Schedule:Constant', {}):
        raise ValueError('Attic ventilation already assigned')
    model.setdefault('Schedule:Constant', {})[schedule] = {'hourly_value': 1}
    objects = model.setdefault('ZoneInfiltration:DesignFlowRate', {})
    for zone in zones:
        objects[f'EPSM_v1_{zone}_outdoor_exchange'] = {
            'zone_or_zonelist_or_space_or_spacelist_name': zone,
            'schedule_name': schedule, 'design_flow_rate_calculation_method': 'AirChanges/Hour',
            'air_changes_per_hour': outdoor_air_ach, 'constant_term_coefficient': 1,
            'temperature_term_coefficient': 0, 'velocity_term_coefficient': 0,
            'velocity_squared_term_coefficient': 0}
    return model
