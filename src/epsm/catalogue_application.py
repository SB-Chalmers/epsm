"""Select frozen LoD2 constructions and apply independent building choices."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from epsm_data import (
    ArchetypeKey,
    ConstructionSet,
    EnvelopePerformance,
    export_nominal_constructions,
)
from epsm_data.domain import BuildingElement as Role

from epsm._logging import operation as logged_operation

from .catalogue_release import _catalogue_view, core_inputs

COMPONENT_FIELDS = {
    "wall": "wall",
    "roof": "top",
    "ground": "ground",
    "basement_wall": "basement_wall",
    "intermediate_floor": "intermediate_floor",
}


def _positive(name, value):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f"{name} must be finite and positive")


def _airflow(envelope, metadata, reference_area, conditioned_volume):
    """Keep area rates native and convert an explicit source-volume convention."""
    if (reference_area is None) != (conditioned_volume is None):
        raise ValueError("Supply both TABULA reference area and conditioned volume")
    if reference_area is not None:
        _positive("tabula_reference_area_m2", reference_area)
        _positive("conditioned_volume_m3", conditioned_volume)
    if envelope is None:
        return None, None, None
    area_rate = envelope.infiltration_l_s_m2
    if area_rate is not None:
        return ({"envelope_infiltration_ach": 0.0,
                 "envelope_infiltration_l_s_m2": area_rate}, None, area_rate)
    ach = envelope.infiltration_ach
    if ach is None:
        return None, None, None
    if envelope.infiltration_reference_basis == "conditioned_volume":
        return {"envelope_infiltration_ach": ach}, None, None
    if reference_area is None:
        return None, None, None
    height = metadata.get("reference_height_m")
    _positive("catalogue reference_height_m", height)
    reference_volume = reference_area * height
    flow_m3_h = ach * reference_volume
    handoff = {
        "source_ach": ach,
        "reference_area_m2": reference_area,
        "reference_height_m": height,
        "reference_volume_m3": reference_volume,
        "conditioned_volume_m3": conditioned_volume,
        "additional_flow_m3_s": flow_m3_h / 3600,
        "additional_flow_l_s_per_reference_m2": ach * height / 3.6,
        "core_envelope_infiltration_ach": flow_m3_h / conditioned_volume,
    }
    return ({"envelope_infiltration_ach": handoff["core_envelope_infiltration_ach"]},
            handoff, None)


@logged_operation("catalogue.resolve")
def resolve_building_archetype(
    *,
    category,
    construction_year,
    climate_zone,
    ventilation=None,
    default_state=None,
    component_states=None,
    component_sources=None,
    detailed=None,
    catalogue=None,
    tabula_reference_area_m2=None,
    conditioned_volume_m3=None,
    weather_shell=None,
):
    """Select shared physical definitions and independently chosen components.

    The catalogue has four building types, seven eras and three climate zones.
    Eras SE.01–SE.06 have existing/standard/advanced variants; SE.07 has one.
    ``ventilation`` is retained in the assignment audit for existing callers;
    it neither selects a catalogue slot nor installs an HVAC system.

    ``component_states`` selects wall, roof, window, ground, basement_wall,
    intermediate_floor or airtightness independently. Each choice requires an
    explicit ``component_sources`` description. Defaults remain assumptions
    about the building, rather than observations of its renovation history.

    TABULA-volume ACH is converted only when both reference area and conditioned
    volume are supplied, using the catalogue's recorded reference height. Native
    area rates keep their declared reference basis. Use core_airflow_inputs when
    constructing Core airflow, and choose its load-reference area explicitly.
    """
    cat = _catalogue_view(catalogue, detailed)
    era = cat.era_for_year(construction_year)
    if era == "SE.07":
        if default_state is not None:
            raise ValueError("SE.07 has no renovation states; use default_state=None")
    elif default_state is None:
        default_state = "existing"
    key = ArchetypeKey(category, era, climate_zone, default_state)
    parent_slot = cat.get_slot(key)
    aid = parent_slot.archetype_id
    states, sources = dict(component_states or {}), dict(component_sources or {})
    selectable = set(COMPONENT_FIELDS) | {"window", "airtightness"}
    if set(states) - selectable:
        raise ValueError("Unknown component-state role")
    if set(sources) != set(states) or any(
        not isinstance(source, str) or not source.strip() for source in sources.values()
    ):
        raise ValueError("Each component selection needs one nonempty independent source")
    native = core_inputs(aid, default_state, catalogue=cat, weather_shell=weather_shell)
    cache = {default_state: native}
    assignments, envelope_updates = {}, {}
    glazing = native["glazing"]
    roof_topology = native["roof_topology"]
    envelope_definition = native["archetype"].envelope_performance
    infiltration_metadata = cat.nominal_metadata(aid, state=default_state)
    for role, state in sorted(states.items()):
        # Validate states against the era without introducing extra catalogue axes.
        cat.get_slot(ArchetypeKey(category, era, climate_zone, state))
        if state not in cache:
            cache[state] = core_inputs(aid, state, catalogue=cat, weather_shell=weather_shell)
        selected = cache[state]
        if role == "window":
            glazing = selected["glazing"]
        elif role == "airtightness":
            envelope_definition = selected["archetype"].envelope_performance
            infiltration_metadata = cat.nominal_metadata(aid, state=state)
        else:
            envelope_updates[COMPONENT_FIELDS[role]] = getattr(
                selected["envelope"], COMPONENT_FIELDS[role]
            )
            if role == "roof":
                roof_topology = selected["roof_topology"]
        assignments[role] = {
            "state": state, "source": sources[role],
            "status": "evidence_selected_catalogue_representative",
        }
    for role in sorted(selectable):
        assignments.setdefault(role, {
            "state": default_state, "source": "catalogue fallback", "status": "assumed",
        })
    core_airflow_inputs, airflow_handoff, area_rate = _airflow(
        envelope_definition, infiltration_metadata,
        tabula_reference_area_m2, conditioned_volume_m3,
    )
    source_ach = envelope_definition.infiltration_ach if envelope_definition else None
    role_names = {
        "wall": Role.EXT_WALL, "roof": Role.TOP_FLOOR,
        "ground": Role.GROUND_FLOOR, "basement_wall": Role.BASEMENT_WALL,
        "intermediate_floor": Role.INTERMEDIATE_FLOOR, "window": Role.WINDOW,
    }
    reference = native["archetype"]
    elements = dict(reference.construction_set.elements)
    role_names["roof"] = Role.TOP_FLOOR if Role.TOP_FLOOR in elements else Role.ROOF
    for role, state in states.items():
        if role in role_names:
            elements[role_names[role]] = cache[state]["archetype"].construction_set.elements[
                role_names[role]
            ]
    if airflow_handoff is not None:
        envelope_definition = EnvelopePerformance(
            infiltration_ach=airflow_handoff["core_envelope_infiltration_ach"],
            infiltration_reference_basis="conditioned_volume",
            thermal_bridge_uplift_fraction=envelope_definition.thermal_bridge_uplift_fraction,
            thermal_bridge_delta_u_w_m2k=envelope_definition.thermal_bridge_delta_u_w_m2k,
            source_references=envelope_definition.source_references,
            notes=envelope_definition.notes + (
                "Explicit catalogue reference-volume to conditioned-volume conversion: "
                + str(airflow_handoff),
            ),
        )
    construction_set = reference.construction_set
    if elements != construction_set.elements:
        physical_roles = {role.value: element.to_dict() for role, element in elements.items()}
        construction_set = ConstructionSet(
            version_id=uuid5(NAMESPACE_URL, "epsm:composed:" + json.dumps(
                physical_roles, sort_keys=True, allow_nan=False,
            )), elements=elements,
        )
    archetype = reference.with_changes(
        construction_set=construction_set,
        envelope_performance=envelope_definition,
        source_references=tuple(dict.fromkeys(
            ref for selected in cache.values() for ref in selected["archetype"].source_references
        )) + tuple(role + ": " + source for role, source in sorted(sources.items())),
        notes=tuple(dict.fromkeys(
            note for selected in cache.values() for note in selected["archetype"].notes
        )) + tuple(
            f"Component {role}: state={assignment['state']}; source={assignment['source']}; "
            f"status={assignment['status']}"
            for role, assignment in sorted(assignments.items())
        ),
    )
    composed_metadata = cat.nominal_metadata(aid, state=default_state)
    composed_metadata["roof_topology"] = roof_topology
    for selected in cache.values():
        composed_metadata["material_references"].update(
            selected["nominal_bundle"]["material_references"]
        )
    # Keep the selected window's link when other roles come from other states.
    # Otherwise multiple window references would make the whole-window mapping
    # ambiguous even though the actual window choice is explicit.
    refs = composed_metadata["material_references"]
    for identifier, ref in list(refs.items()):
        if (ref.get("kind") in {"simple_window", "window"}
                or identifier.startswith(("window_", "window:"))):
            del refs[identifier]
    for identifier, ref in cat.nominal_metadata(
        aid, state=states.get("window", default_state)
    )["material_references"].items():
        if (ref.get("kind") in {"simple_window", "window"}
                or identifier.startswith(("window_", "window:"))):
            refs[identifier] = ref
    for role, state in states.items():
        if role in role_names:
            role_name = role_names[role].value
            details = cat.nominal_metadata(aid, state=state).get("boundary_details", {})
            composed_metadata.setdefault("boundary_details", {})[role_name] = deepcopy(
                details.get(role_name, {})
            )
    return {
        "archetype": archetype,
        "envelope": native["envelope"].updated(**envelope_updates),
        "glazing": glazing,
        "roof_topology": roof_topology,
        "nominal_bundle": export_nominal_constructions(archetype, metadata=composed_metadata),
        "infiltration_ach": (core_airflow_inputs["envelope_infiltration_ach"]
                             if core_airflow_inputs is not None else source_ach),
        "infiltration_l_s_m2": area_rate,
        "core_airflow_inputs": core_airflow_inputs,
        "infiltration_source_ach": source_ach,
        "airflow_handoff": airflow_handoff,
        "infiltration_reference_basis": "atemp_area_rate" if area_rate is not None
        else "core_conditioned_volume" if core_airflow_inputs is not None
        else "tabula_reference_volume_conversion_required",
        "assignment": {
            "archetype_id": aid, "category": category, "era": era,
            "climate_zone": climate_zone, "ventilation": ventilation,
            "components": assignments,
        },
        "component_nominal_bundles": {
            state: deepcopy(selected["nominal_bundle"]) for state, selected in cache.items()
        },
        "requirements": dict(
            native["requirements"],
            operation="Select a Core use profile or documented building operation",
            geometry="Supply physical extent, footprint, storeys, Atemp and exposed walls",
            ventilation="Supply installed ventilation flow, schedule and heat recovery",
            infiltration="Use core_airflow_inputs with the declared area or volume basis",
            climate="Select weather independently of the catalogue climate-zone assignment",
            state="Default existing is an assumed construction choice",
        ),
    }
