"""Frozen Data catalogue handovers preserve physical inputs in EPSM and Core."""

from copy import deepcopy

import pytest
from epsm_core import Footprint
from epsm_core.specs import ConstructionSpec
from epsm_data import Catalogue, validate_nominal_handover
from epsm_data.domain import BuildingElement as Role

from epsm import Building
from epsm.catalogue_application import resolve_building_archetype
from epsm.catalogue_release import core_inputs


@pytest.fixture(scope="module")
def catalogue():
    return Catalogue.load()


def test_every_frozen_configuration_has_native_core_handover(catalogue):
    configurations = {
        (slot.archetype_id, slot.state)
        for slot in catalogue.search(climate_zone="SE.Zone3")
    }
    assert len(configurations) == 76
    for identifier, state in sorted(configurations, key=lambda item: str(item)):
        native = core_inputs(identifier, state, catalogue=catalogue)
        bundle = native["nominal_bundle"]
        assert validate_nominal_handover(bundle) == {"honeybee": True, "core": True}
        for role, record in bundle["core"].items():
            if role != "WINDOW":
                construction = ConstructionSpec(**record)
                assert construction.u_value_w_m2k == pytest.approx(
                    bundle["roles"][role]["nominal_u_w_m2k"], rel=1e-10,
                )
        assert native["envelope"].wall.u_value_w_m2k == pytest.approx(
            bundle["roles"]["EXT_WALL"]["nominal_u_w_m2k"]
        )
        assert native["glazing"].u_value_w_m2k == bundle["roles"]["WINDOW"]["nominal_u_w_m2k"]


def test_representative_weather_shell_stays_explicit_and_can_be_overridden(catalogue):
    native = core_inputs("mf_se02", catalogue=catalogue)
    shell = native["envelope"].weather_shell
    assert [layer.thickness_m for layer in shell.layers] == [0.003, 0.022]
    assert "representative" in native["requirements"]["weather_shell"].lower()
    replacement = native["envelope"].top
    changed = core_inputs("mf_se02", catalogue=catalogue, weather_shell=replacement)
    assert changed["envelope"].weather_shell == replacement
    assert changed["envelope"].top == native["envelope"].top
    assert "Caller-supplied" in changed["requirements"]["weather_shell"]


def test_legacy_attic_adapter_rejects_native_double_counting():
    from epsm.catalogue_release import apply_attic_ventilation

    model = {
        "Zone": {"main_attic": {"part_of_total_floor_area": "No"}},
        "ZoneInfiltration:DesignFlowRate": {
            "native": {"zone_or_zonelist_or_space_or_spacelist_name": "main_attic"}
        },
    }
    with pytest.raises(ValueError, match="already assigned"):
        apply_attic_ventilation(model, outdoor_air_ach=0.5)


def test_ventilation_is_audit_context_without_multiplying_physical_slots(catalogue):
    options = dict(category="multi_family", construction_year=1970,
                   climate_zone="SE.Zone3", catalogue=catalogue)
    extract = resolve_building_archetype(**options, ventilation="F")
    recovery = resolve_building_archetype(**options, ventilation="FTX")
    assert extract["archetype"].construction_set == recovery["archetype"].construction_set
    assert extract["envelope"] == recovery["envelope"]
    assert extract["assignment"]["ventilation"] == "F"
    assert recovery["assignment"]["ventilation"] == "FTX"
    # The observed system selects only the airflow template.
    assert extract["archetype"].hvac_template.template_id == "epsm.ventilation.F"
    assert recovery["archetype"].hvac_template.to_dict()["values"]["airflow"]["topology"] == "FTX"
    assert len(catalogue.search()) == 228


def test_mixed_components_preserve_others_and_have_repeatable_identity(catalogue):
    options = dict(category="multi_family", construction_year=1970,
                   climate_zone="SE.Zone3", catalogue=catalogue)
    baseline = resolve_building_archetype(**options)
    selections = dict(component_states={"window": "advanced"},
                      component_sources={"window": "survey:replacement-window"})
    selected = resolve_building_archetype(**options, **selections)
    repeated = resolve_building_archetype(**options, **selections)
    old = baseline["archetype"].construction_set
    new = selected["archetype"].construction_set
    assert new.elements[Role.WINDOW] != old.elements[Role.WINDOW]
    for role in set(old.elements) - {Role.WINDOW}:
        assert new.elements[role] == old.elements[role]
    assert selected["core_airflow_inputs"] == baseline["core_airflow_inputs"]
    assert new.version_id == repeated["archetype"].construction_set.version_id
    assert new.version_id != old.version_id
    assert selected["nominal_bundle"]["core"]["WINDOW"]["u_value_w_m2k"] == selected["glazing"].u_value_w_m2k
    assert validate_nominal_handover(selected["nominal_bundle"])
    expected_window_link = core_inputs("mf_se02", "advanced", catalogue=catalogue)[
        "nominal_bundle"
    ]["roles"]["WINDOW"]["window_reference"]
    assert expected_window_link.get("honeybee_id")
    assert selected["nominal_bundle"]["roles"]["WINDOW"]["window_reference"] == expected_window_link


def test_source_volume_and_native_area_infiltration_keep_their_meaning(catalogue):
    options = dict(construction_year=1970, climate_zone="SE.Zone3", catalogue=catalogue)
    unresolved = resolve_building_archetype(category="single_family", **options)
    assert unresolved["core_airflow_inputs"] is None
    assert unresolved["infiltration_reference_basis"] == "tabula_reference_volume_conversion_required"
    converted = resolve_building_archetype(
        category="single_family", **options,
        tabula_reference_area_m2=125, conditioned_volume_m3=480,
    )
    source = converted["infiltration_source_ach"]
    assert converted["airflow_handoff"]["reference_height_m"] == 2.5
    assert converted["core_airflow_inputs"]["envelope_infiltration_ach"] == pytest.approx(
        source * 2.5 * 125 / 480
    )
    assert converted["archetype"].envelope_performance.infiltration_reference_basis == "conditioned_volume"
    area = resolve_building_archetype(category="multi_family", **options)
    assert area["core_airflow_inputs"] == {
        "envelope_infiltration_ach": 0.0,
        "envelope_infiltration_l_s_m2": 0.2,
    }
    assert area["archetype"].envelope_performance.infiltration_reference_basis == "Atemp"


def test_public_building_application_preserves_geometry_and_leaves_hvac_explicit(catalogue):
    archetype = catalogue.get("mf_se02")
    building = Building.from_footprint(
        Footprint.rectangle(10, 8), storeys=2, storey_height_m=3,
        load_reference_area_m2=125,
    )
    original_geometry = deepcopy(building.geometry.model_dump(mode="json"))
    report = building.apply_archetype(archetype, calendar={"calendar_year": 2024})
    assert building.geometry.model_dump(mode="json") == original_geometry
    assert building.construction_set.elements
    for role, construction in building.construction_set.elements.items():
        assert construction == archetype.construction_set.elements[role]
    # Only the archetype's airflow template is installed; heating stays explicit.
    assert building.hvac.airflow.topology == archetype.hvac_template.to_dict()[
        "values"]["airflow"]["topology"]
    assert building.hvac.delivery.heating is None
    assert report.archetype_id == archetype.archetype_id
    assert building.operation is not None
    restored = Building.from_dict(building.to_dict())
    assert restored.construction_set == building.construction_set


def test_se07_has_one_variant_and_invalid_classifications_fail(catalogue):
    newest = resolve_building_archetype(
        category="office", construction_year=2024, climate_zone="SE.Zone1", catalogue=catalogue,
    )
    assert newest["assignment"]["components"]["wall"]["state"] is None
    with pytest.raises(ValueError, match="SE.07"):
        core_inputs("office_se07", "existing", catalogue=catalogue)
    with pytest.raises(ValueError, match="climate_zone"):
        resolve_building_archetype(
            category="office", construction_year=1970,
            climate_zone="unknown", catalogue=catalogue,
        )
