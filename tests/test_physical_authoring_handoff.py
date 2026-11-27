"""New physical authoring remains available through the public EPSM Building."""

import json

import pytest
from epsm_data.domain import BuildingElement as Role

from epsm import Building


def test_insulation_authoring_roundtrips_without_an_epsm_wrapper():
    building = Building(preset="illustrative-reference")
    original = building.to_dict()
    wall = next(element for element in building.elements if element.role == Role.EXT_WALL)
    component = wall.construction.components[0]
    before_id = wall.identifier
    before_occurrences = tuple(element.component_ids for element in building.elements)

    assert building.assign_element_u_value(
        0.2, component_name=component.name, layer_index=0,
        element_ids=[wall.identifier],
    ) is building
    saved = json.loads(json.dumps(building.to_dict()))
    restored = Building.from_dict(saved)
    changed = next(element for element in restored.elements if element.identifier == before_id)
    assert changed.construction.u_value == pytest.approx(0.2)
    assert restored.to_dict() == saved
    assert saved["assessment"] == original["assessment"]
    assert saved["source_record"] == original["source_record"]
    assert tuple(element.component_ids for element in restored.elements) == before_occurrences
    assert not restored.lineage_to_dict().get("stages")
    assert original["building"] != saved["building"]
