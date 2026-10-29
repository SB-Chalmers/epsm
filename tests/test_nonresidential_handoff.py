"""All school/office variants agree across public physical and legacy routes."""

# ruff: noqa: F811

from datetime import date, timedelta

import pytest
from epsm_core import Footprint, GeometrySpec, RoofSpec, ZoningSpec
from epsm_data import Catalogue
from epsm_data.domain import BuildingElement as Role
from test_platform import weather  # noqa: F401

from epsm import Building
from epsm.catalogue_application import resolve_building_archetype
from epsm.catalogue_release import core_inputs

CATALOGUE = Catalogue.load()
CONFIGURATIONS = sorted(
    {(slot.archetype_id, slot.state)
     for slot in CATALOGUE.search(climate_zone="SE.Zone3")
     if slot.archetype_id.startswith(("school_", "office_"))},
    key=str,
)


def physics(construction):
    result = construction.model_dump(mode="json")
    for layer in result["layers"]:
        layer["material"].pop("name")
    def rounded(value):
        if isinstance(value, float):
            return round(value, 9)
        if isinstance(value, dict):
            return {key: rounded(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rounded(item) for item in value]
        return value
    return rounded(result)


@pytest.mark.parametrize("identifier,state", CONFIGURATIONS)
@pytest.mark.parametrize("basement", ["absent", "heated", "unheated"])
def test_public_and_legacy_boundaries_agree(identifier, state, basement, weather):
    """Illustrative non-construction inputs allow actual to_spec conversion."""
    native = core_inputs(identifier, state, catalogue=CATALOGUE)
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        roof=(RoofSpec(shape="gable", pitch_deg=30)
              if native["roof_topology"] == "cold_attic" else RoofSpec(shape="flat")),
        basement_depth_m=2 if basement != "absent" else 0,
        basement_conditioned=basement == "heated",
        zoning=ZoningSpec(mode="per_storey"),
    )
    building = Building(preset="illustrative-reference", geometry=geometry,
                        load_reference_area_m2=140)
    day, active_dates = date(2023, 1, 1), []
    while len(active_dates) < native["archetype"].operating_profile.values["reference_active_days"]:
        if day.weekday() < 5:
            active_dates.append(day.isoformat())
        day += timedelta(days=1)
    report = building.apply_archetype(native["archetype"], calendar={
        "calendar_year": 2023, "active_dates": active_dates,
        "calendar_source": "Explicit synthetic construction-handoff test calendar",
    })
    assert building.geometry == geometry
    assert all(element.construction is not None for element in building.elements)
    assert not any(item.startswith("construction:") for item in building.readiness().missing)
    assert report.archetype_id == identifier
    spec = building.to_spec(weather)
    fields = ["wall", "top", "ground", "intermediate_floor"]
    if basement != "absent":
        fields.append("basement_wall")
    for field in fields:
        assert physics(getattr(spec.envelope, field)) == physics(getattr(native["envelope"], field))
    if "BASEMENT_FLOOR" in native["nominal_bundle"]["core"]:
        soil_id = "main.ground_floor" if basement == "absent" else "main.basement_floor"
        assert next(e for e in building.elements if e.identifier == soil_id).role == Role.BASEMENT_FLOOR
        if basement != "absent":
            assert physics(spec.envelope.basement_ceiling) == physics(native["envelope"].basement_ceiling)
            assert physics(spec.envelope.ground) != physics(spec.envelope.basement_ceiling)
    if native["roof_topology"] == "cold_attic":
        assert physics(spec.envelope.weather_shell) == physics(native["envelope"].weather_shell)


@pytest.mark.parametrize("category", ["school", "office"])
def test_ground_component_selection_retains_separate_slab_and_ceiling(category):
    options = dict(category=category, construction_year=1930, climate_zone="SE.Zone3",
                   catalogue=CATALOGUE)
    selected = resolve_building_archetype(
        **options, component_states={"ground": "advanced"},
        component_sources={"ground": "test:documented-foundation-work"},
    )
    expected = core_inputs(f"{category}_se01", "advanced", catalogue=CATALOGUE)
    for role in (Role.GROUND_FLOOR, Role.BASEMENT_FLOOR):
        assert selected["archetype"].construction_set.elements[role] == expected["archetype"].construction_set.elements[role]
    for field in ("ground", "basement_ceiling"):
        assert getattr(selected["envelope"], field) == getattr(expected["envelope"], field)

