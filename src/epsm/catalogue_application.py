"""Evidence-led composition of matrix components for an actual building.

References: EPSM Data LoD2 v1.3 evidence/claims and release.core_inputs.
The packaged matrix is a frozen construction library, not a set of fitted EPC
predictions. Component states are selected from independent building evidence;
heating observations and prediction residuals are never inputs to this resolver.
Nominal ground constructions are handed to Core; soil/boundaries remain explicit.
"""

from __future__ import annotations

from copy import deepcopy

from epsm_data.detailed import load_detailed_catalogue
from epsm_data.parametric import ArchetypeKey, era_for_year, load_parametric_catalogue

from .catalogue_release import core_inputs

COMPONENT_FIELDS = {
    "wall": "wall",
    "roof": "top",
    "ground": "ground",
    "basement_wall": "basement_wall",
    "intermediate_floor": "intermediate_floor",
}


def resolve_building_archetype(
    *,
    category,
    construction_year,
    climate_zone,
    ventilation,
    default_state=None,
    component_states=None,
    component_sources=None,
    detailed=None,
    catalogue=None,
    tabula_reference_area_m2=None,
    conditioned_volume_m3=None,
):
    """Select a matrix parent and independently evidenced component states.

    Parameters
    ----------
    category : str
        single_family, multi_family, office, school or generic.
    construction_year : int
        Known construction year mapped through the catalogue's declared seven eras.
    climate_zone, ventilation : str
        Explicit catalogue classifications; no location or HVAC inference occurs.
    default_state : str
        Shared fallback existing/standard/advanced, recorded as an assumption.
        Existing means original-era fabric, not evidence that no renovation occurred.
    component_states, component_sources : dict or None
        Maps wall, roof, window, ground, basement_wall, intermediate_floor or
        airtightness to states and independent source descriptions. A source is
        required for every component selection. Replacing a window does not
        silently modify airtightness or any opaque construction.

    tabula_reference_area_m2, conditioned_volume_m3 : float or None
        Supply both to preserve TABULA's reference-volume airflow in Core. The
        reference area needs an explicit documented mapping; 2.5 m is TABULA's
        calculation height, not the building's measured clear height. Without
        these inputs, infiltration_ach retains the source-reference ACH and must
        not be passed directly to Core with a different volume.

    MF area-based defaults expose core_airflow_inputs for native Core handoff;
    set Core load reference area to Atemp. infiltration_ach remains a legacy
    representation; use core_airflow_inputs rather than passing it directly.

    Returns
    -------
    dict
        Native Core fabric, independent infiltration, classification/assignment
        audit and unresolved building requirements. Never a complete BuildingSpec
        or an assertion of building-level accuracy. Input datasets are not mutated.
    """
    cat = catalogue or load_parametric_catalogue()
    data = detailed or load_detailed_catalogue(catalogue=cat)
    era = era_for_year(construction_year)
    if era == "SE.07":
        if default_state is not None:
            raise ValueError("SE.07 has no renovation states; use default_state=None")
    elif default_state is None:
        default_state = "existing"
    key = ArchetypeKey(category, era, climate_zone, default_state, ventilation)
    parent_slot = cat.get_slot(key)  # validates every classification and state
    candidates = [
        aid
        for aid, definition in data.archetypes.items()
        if definition.get("catalogue_assignment", "canonical") == "canonical"
        and definition["category"] == category
        and definition["era"] == era
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Expected one canonical matrix parent for {category}/{era}; found {candidates}"
        )
    aid = candidates[0]
    states = dict(component_states or {})
    sources = dict(component_sources or {})
    if set(states) - (set(COMPONENT_FIELDS) | {"window", "airtightness"}):
        raise ValueError("Unknown component-state role")
    if set(sources) != set(states) or any(
        not isinstance(s, str) or not s.strip() for s in sources.values()
    ):
        raise ValueError("Each component selection needs one nonempty independent source")
    native = core_inputs(aid, default_state, detailed=data, catalogue=cat)
    cache = {default_state: native}
    assignments = {}
    envelope_updates = {}
    glazing = native["glazing"]
    infiltration = parent_slot.infiltration
    for role, state in sorted(states.items()):
        slot = cat.get_slot(ArchetypeKey(category, era, climate_zone, state, ventilation))
        if state not in cache:
            cache[state] = core_inputs(aid, state, detailed=data, catalogue=cat)
        selected = cache[state]
        if role == "window":
            glazing = selected["glazing"]
        elif role == "airtightness":
            infiltration = slot.infiltration
        else:
            envelope_updates[COMPONENT_FIELDS[role]] = getattr(
                selected["envelope"], COMPONENT_FIELDS[role]
            )
        assignments[role] = {
            "state": state,
            "source": sources[role],
            "status": "evidence_selected_catalogue_representative",
        }
    for role in set(COMPONENT_FIELDS) | {"window", "airtightness"}:
        assignments.setdefault(
            role, {"state": default_state, "source": "matrix fallback", "status": "assumed"}
        )
    # TABULA equation (7), printed pp.12–13; see packaged airflow_review.json.
    # Do not multiply a source-reference ACH by arbitrary model geometry volume.
    if (tabula_reference_area_m2 is None) != (conditioned_volume_m3 is None):
        raise ValueError("Supply both TABULA reference area and conditioned volume")
    airflow_handoff = None
    if tabula_reference_area_m2 is not None:
        from epsm_data.airflow import infiltration_handoff

        airflow_handoff = infiltration_handoff(
            infiltration, reference_area_m2=tabula_reference_area_m2,
            conditioned_volume_m3=conditioned_volume_m3,
        )
    # EPSM MF review 2026-10-04: native q is per Atemp, independently of
    # Core zone volume. Legacy TABULA categories still need volume conversion.
    basis = (infiltration.evidence or {}).get("airflow_basis", {})
    area_rate = basis.get("additional_flow_l_s_per_reference_m2")
    if (infiltration.evidence or {}).get("basis_stale"):
        area_rate = None
    core_airflow_inputs = (
        {"envelope_infiltration_ach": 0.0, "envelope_infiltration_l_s_m2": area_rate}
        if area_rate is not None else
        {"envelope_infiltration_ach": airflow_handoff["core_envelope_infiltration_ach"]}
        if airflow_handoff else None
    )
    return {
        "envelope": native["envelope"].updated(**envelope_updates),
        "glazing": glazing,
        "roof_topology": native["roof_topology"],
        "infiltration_ach": (
            airflow_handoff["core_envelope_infiltration_ach"]
            if airflow_handoff else infiltration.value
        ),
        "infiltration_l_s_m2": area_rate,
        "core_airflow_inputs": core_airflow_inputs,
        "infiltration_source_ach": infiltration.value,
        "airflow_handoff": airflow_handoff,
        "infiltration_reference_basis": "atemp_area_rate" if area_rate is not None else "core_conditioned_volume" if airflow_handoff else "tabula_reference_volume_conversion_required",
        "assignment": {
            "archetype_id": aid,
            "category": category,
            "era": era,
            "climate_zone": climate_zone,
            "ventilation": ventilation,
            "components": assignments,
        },
        "component_nominal_bundles": {s: deepcopy(b["nominal_bundle"]) for s, b in cache.items()},
        "requirements": dict(
            native["requirements"],
            operation="Select a versioned Core use profile or documented building operation",
            geometry="Verify physical extent, footprint, storeys, Atemp and exposed walls",
            ventilation="Explicit mechanical/natural flow, schedule and recovery; exhaust pressure coupling remains unresolved",
            infiltration="Use core_airflow_inputs. MF area rates require explicit Atemp as Core load reference area; other categories require reviewed source-volume conversion. Office/school are residential proxies.",
            thermal_bridges="Review inclusion in source constructions before applying uplift",
            climate="Measurement-compatible year/weather and an audited climate-zone mapping",
            energy_boundary="Match ideal thermal demand to the observed delivered-energy field",
            state="Fallback existing is not evidence of an unrenovated building",
            empirical_validation="pending; component composition is not an EPC calibration",
        ),
    }
