"""Platform handoffs preserve the explicit unknown-type/MF assumption."""

import json

import pytest
from epsm_data import (
    Catalogue,
    archetype_from_dict,
    archetype_to_dict,
    validate_nominal_handover,
)
from epsm_data.classification import ERAS, ZONES, states_for_era

from epsm.catalogue_application import resolve_building_archetype
from epsm.catalogue_release import core_inputs

LABEL = "Unknown building type — multifamily assumption"
CASES = [
    (era, start, state)
    for era, (start, _) in ERAS.items()
    for state in states_for_era(era)
]


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue.load()


@pytest.mark.parametrize("era,year,state", CASES)
def test_generic_handoff_uses_matching_mf_config_in_every_zone(
    catalogue, era, year, state
):
    donor = catalogue.for_year("multi_family", year, state=state)
    expected = core_inputs(donor.archetype_id, state, catalogue=catalogue)
    for zone in ZONES:
        result = resolve_building_archetype(
            category="generic",
            construction_year=year,
            climate_zone=zone,
            default_state=state,
            catalogue=catalogue,
        )
        archetype = result["archetype"]
        assert archetype.construction_set is donor.construction_set
        assert archetype.operating_profile is donor.operating_profile
        assert archetype.display_name == LABEL
        assert result["envelope"] == expected["envelope"]
        assert result["glazing"] == expected["glazing"]
        assert result["nominal_bundle"]["core"] == expected["nominal_bundle"]["core"]
        assignment = result["assignment"]
        assert assignment["category"] == "generic"
        assert assignment["climate_zone"] == zone
        assert assignment["archetype_id"] == donor.archetype_id
        assert assignment["requested_archetype_id"] == "generic_se" + era.removeprefix(
            "SE."
        )
        assert assignment["selection"]["requested_category"] == "generic"
        assert assignment["selection"]["donor_category"] == "multi_family"
        assert assignment["selection"]["donor_archetype_id"] == donor.archetype_id
        assert assignment["selection"]["assumption_label"] == LABEL
        assert result["nominal_bundle"]["selection"] == assignment["selection"]
        assert validate_nominal_handover(result["nominal_bundle"]) == {
            "honeybee": True,
            "core": True,
        }
        assert "geometry" in result["requirements"]
        assert "ventilation" in result["requirements"]
        # The donor's era-default ventilation template; no system was observed.
        assert archetype.hvac_template == donor.hvac_template
        assert all(
            item["state"] == state
            for item in result["assignment"]["components"].values()
        )


def test_generic_component_intervention_preserves_selection_audit(catalogue):
    choices = dict(
        construction_year=1970,
        climate_zone="SE.Zone2",
        catalogue=catalogue,
        component_states={"window": "advanced"},
        component_sources={"window": "independent survey: replacement glazing"},
    )
    generic = resolve_building_archetype(category="generic", **choices)
    mf = resolve_building_archetype(category="multi_family", **choices)
    assert generic["archetype"].construction_set == mf["archetype"].construction_set
    assert generic["nominal_bundle"]["core"] == mf["nominal_bundle"]["core"]
    assert generic["nominal_bundle"]["selection"]["donor_archetype_id"] == "mf_se02"
    portable = json.loads(json.dumps(generic["assignment"]))
    assert portable["selection"]["assumption_label"] == LABEL
    restored = archetype_from_dict(archetype_to_dict(generic["archetype"]))
    assert restored.display_name == LABEL
    assert restored.building_typology == "generic"
    assert restored.notes == generic["archetype"].notes


def test_direct_generic_core_handoff_has_explicit_label_and_profile(catalogue):
    native = core_inputs("generic_se07", catalogue=catalogue)
    assert native["archetype"].display_name == LABEL
    assert native["selection"]["donor_archetype_id"] == "mf_se07"
    assert (
        native["archetype"].operating_profile
        is catalogue.get("mf_se07").operating_profile
    )
    assert native["nominal_bundle"]["category"] == "generic"
    with pytest.raises(ValueError, match="SE.07"):
        core_inputs("generic_se07", "existing", catalogue=catalogue)
