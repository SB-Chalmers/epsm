"""Explicit v1 construction handover; optional core dependencies are imported lazily."""
from __future__ import annotations

import math
from copy import deepcopy

from epsm_data.detailed import load_detailed_catalogue
from epsm_data.layered import load_calibrated_archetype
from epsm_data.parametric import load_parametric_catalogue


def core_inputs(archetype_id, state=None, *, detailed=None, catalogue=None, basement_wall=None):
    """Return native core envelope/glazing plus topology and boundary requirements.

    Callers supply geometry, weather, use, HVAC and ground temperatures. An explicit
    attic outdoor-air rate is required for cold attics. Current Core accepts
    UnconditionedExchangeSpec; apply_attic_ventilation supports legacy compilers.
    Baseline and renovation describe independent states, not sequential operations.
    """
    from epsm_core.specs import ConstructionSpec, EnvelopeSpec, GlazingSpec

    detailed = detailed or load_detailed_catalogue()
    catalogue = catalogue or load_parametric_catalogue()
    if detailed.archetypes[archetype_id]['era'] == 'SE.07':
        if state is not None:
            raise ValueError('SE.07 has no renovation states; use state=None')
    elif state is None:
        state = 'existing'
    definition = detailed.archetypes[archetype_id]['states'][state]
    if definition.get('release_profile') not in {'lod2-v1', 'complete_recipe'}:
        raise ValueError('This adapter requires a reviewed v1 state')
    model = load_calibrated_archetype(detailed=detailed, catalogue=catalogue,
                                     archetype_id=archetype_id, renovation_state=state)
    bundle = model.to_nominal_dict()
    core = bundle['core']
    roof = definition['v1_review']['roof_topology']
    # Representative non-insulated weather shell: outside felt, then roof boarding.
    # Required only for an attic; it must never carry the ceiling insulation again.
    stack = []
    for mid, thickness in [('office_under_felt', .003), ('wooden_stud', .022)]:
        p = detailed.resolve_material(mid)['properties']
        stack.append({'thickness_m': thickness, 'material': {
            'name': f'v1_weather_{mid}', 'conductivity_w_mk': p['conductivity'],
            'density_kg_m3': p['density'], 'specific_heat_j_kgk': p['specific_heat'],
            'roughness': p['roughness'], 'thermal_absorptance': p['thermal_absorptance'],
            'solar_absorptance': p['solar_absorptance'], 'visible_absorptance': p['visible_absorptance']}})
    top = ConstructionSpec(**core.get('TOP_FLOOR', core.get('ROOF')))
    ground = ConstructionSpec(**core['GROUND_FLOOR'])
    if 'BASEMENT_WALL' in core:
        basement_wall = ConstructionSpec(**core['BASEMENT_WALL'])
    elif basement_wall is None:
        raise ValueError('No basement-wall recipe: this core requires an explicit basement_wall construction; no floor substitution is made.')
    envelope = EnvelopeSpec(wall=ConstructionSpec(**core['EXT_WALL']), top=top,
        ground=ground, intermediate_floor=ConstructionSpec(**core['INTERMEDIATE_FLOOR']),
        weather_shell=ConstructionSpec(layers=tuple(stack)),
        basement_wall=basement_wall)
    return {'envelope': envelope, 'glazing': GlazingSpec(**core['WINDOW']),
            'roof_topology': roof, 'nominal_bundle': bundle,
            'requirements': {
                'attic_outdoor_air_ach': 'required explicit assumption' if roof == 'cold_attic' else 'not applicable',
                'weather_shell': 'Representative 3 mm felt + 22 mm timber; assumed, not inferred from ceiling U.',
                'ground_temperature': 'Caller must supply ground boundary; core default is not validated.',
                'basement': 'Optional construction; geometry determines presence. No floor substitution is supplied.',
                'empirical_validation': 'pending'}}


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
