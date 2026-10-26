"""Maintained consumers select portable Data definitions and preserve physical inputs."""

import hashlib
import json
from pathlib import Path

import pytest
from epsm_core import Footprint, GeometrySpec
from epsm_data import Catalogue
from shapely.geometry import box

from epsm import Building

# Captured from the original pre-migration legacy_records._operation; all eight
# raw fingerprints were verified before normalizing only float representation.
# Keep every field, source and schedule position; nine decimal places are below
# source precision and tolerate Python 3.12's improved annual float summation.
BASELINES = {
    (
        "residential",
        2023,
    ): "d30771c333aa89ddefd959818f21f6df93f8d38cab078c75fb73a117d7f727da",
    (
        "residential",
        2024,
    ): "4a0f09f9bbca62e6d2f00ea5e279f6ff108cc6b99c151a17a1829461ae71ed9c",
    (
        "office",
        2023,
    ): "1ef4315f6ff0f4504c61e17353bfdf92c0de3323ccc33d385c1b0c8b8a1e6d80",
    (
        "office",
        2024,
    ): "887c96fc17e97a5a03f12a10aec1c42727ea3d4f13067d2dcb182d84acfac350",
    (
        "school",
        2023,
    ): "89250820931150b24f303917cc42dedc5012c6cb60caee9c694dfb555bbd0e5f",
    (
        "school",
        2024,
    ): "9577bf3ed22c9557abcda9b64026a96cb255bd9d739b6339fc7065609a2de9c5",
    ("other", 2023): "3575dca5259247ae0a1a00d13e7a5d98110f19a2aeb068be114530fc3f27104c",
    ("other", 2024): "3575dca5259247ae0a1a00d13e7a5d98110f19a2aeb068be114530fc3f27104c",
}


def normalized_physical_values(value):
    if isinstance(value, float):
        return round(value, 9)
    if isinstance(value, dict):
        return {key: normalized_physical_values(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [normalized_physical_values(item) for item in value]
    return value


@pytest.mark.parametrize("name,year", BASELINES)
def test_legacy_programme_uses_public_definition_conversion_with_same_outputs(
    name, year, monkeypatch
):
    pytest.importorskip("sweden_ubem")
    import epsm_core
    from sweden_ubem.records import Receipt

    from epsm.legacy_records import ModelPolicy, _operation

    def denied(*args, **kwargs):
        pytest.fail(
            "Consumer must select profiles in Data and use the public Core converter"
        )

    resolver = epsm_core.resolve_operating_profile
    converted = []

    def resolve(profile, **options):
        converted.append(profile.profile_id)
        return resolver(profile, **options)

    monkeypatch.setattr(epsm_core, "resolve_operating_profile", resolve)
    for loader in (
        "load_dhw_profile",
        "load_generic_other_v1",
        "load_sveby_office_v1",
        "load_sveby_school_v1",
        "load_sveby_spec",
    ):
        if hasattr(epsm_core, loader):
            monkeypatch.setattr(epsm_core, loader, denied)
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 10), storeys=1, storey_height_m=3
    )
    use, air, source = _operation(
        name,
        year,
        ventilation="FTX",
        infiltration={"envelope_infiltration_ach": 0.2},
        geometry=geometry,
        area=90,
        policy=ModelPolicy(),
        receipt=Receipt("test"),
    )
    assert converted == source.split(" + ")
    payload = {
        "use": use.model_dump(mode="json"),
        "airflow": air.model_dump(mode="json"),
        "source": source,
    }
    assert (
        hashlib.sha256(
            json.dumps(
                normalized_physical_values(payload), sort_keys=True, allow_nan=False
            ).encode()
        ).hexdigest()
        == BASELINES[name, year]
    )


@pytest.mark.parametrize("name", ["residential", "office"])
@pytest.mark.parametrize("year", [2023, 2024])
def test_programme_preservation_under_python_311_summation(name, year, monkeypatch):
    import epsm_core.nonresidential as nonresidential
    import epsm_core.standards as residential

    def historical_sum(items, start=0):
        result = start
        for item in items:
            result += item
        return result

    monkeypatch.setattr(residential, "sum", historical_sum, raising=False)
    monkeypatch.setattr(nonresidential, "sum", historical_sum, raising=False)
    test_legacy_programme_uses_public_definition_conversion_with_same_outputs(
        name, year, monkeypatch
    )


@pytest.mark.parametrize("name,expected_hours", [("office", 2700), ("school", 2200)])
@pytest.mark.parametrize("year", [2023, 2024])
def test_natural_ventilation_preserves_normal_use_closures(name, expected_hours, year):
    """Changing the topology must not turn occupied-hours flow into 24/7 flow."""
    pytest.importorskip("sweden_ubem")
    import numpy as np
    from sweden_ubem.records import Receipt

    from epsm.legacy_records import ModelPolicy, _operation

    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 10), storeys=1, storey_height_m=3
    )
    options = dict(
        infiltration={"envelope_infiltration_ach": 0.2},
        geometry=geometry,
        area=90,
        policy=ModelPolicy(),
    )
    _, mechanical, _ = _operation(
        name, year, ventilation="FTX", receipt=Receipt("mechanical"), **options
    )
    receipt = Receipt("natural")
    _, natural, _ = _operation(name, year, ventilation="S", receipt=receipt, **options)
    schedule = natural.natural_exchange_fraction.hourly(year)
    np.testing.assert_array_equal(
        schedule, mechanical.mechanical_vent_fraction.hourly(year)
    )
    assert sum(schedule) == expected_hours
    assert schedule[0] == 0  # Midnight is outside either operating programme.
    assert natural.mechanical_vent_l_s_m2 == 0
    assert (
        natural.natural_exchange_ach * geometry.conditioned_volume_m3 / 3.6
        == pytest.approx(mechanical.mechanical_vent_l_s_m2 * 90)
    )
    assert natural.sensible_recovery_effectiveness == 0
    assert natural.envelope_infiltration_ach == 0.2
    assert any("equivalent-flow assumption" in item for item in receipt.assumptions)


def test_record_archetype_route_preserves_independent_evidence_and_area():
    record = {
        "building_id": "survey-one",
        "geometry": box(0, 0, 10, 8),
        "facts": {"storeys": 2, "storey_height_m": 3},
        "atemp_m2": 125,
        "observations": ({"source_field": "window_year", "raw_values": [2001]},),
    }
    original = dict(record)
    archetype = Catalogue.load().for_year("multi_family", 1960)
    building = Building.from_record(
        record,
        archetype=archetype,
        calendar={"calendar_year": 2024},
        load_reference_area_m2=125,
    )
    assert building.geometry.conditioned_floor_area_m2 == 160
    assert building.load_reference_area_m2 == 125
    assert building._source_record["observations"] == record["observations"]
    assert building.archetype_applications[0].archetype_id == archetype.archetype_id
    assert building.operation is not None
    assert (
        building.hvac.airflow.topology
        == archetype.hvac_template.to_dict()["values"]["airflow"]["topology"]
    )
    assert building.hvac.delivery.heating is None
    assert record == original
    assert (
        Building.from_dict(building.to_dict()).archetype_applications[0].to_dict()
        == building.archetype_applications[0].to_dict()
    )


def test_record_without_archetype_remains_unassigned():
    building = Building.from_record({"building_id": "incomplete"})
    assert building.construction_set is None and building.archetype_applications == ()
    with pytest.raises(ValueError, match="calendar"):
        Building.from_record(
            {"building_id": "incomplete"}, calendar={"calendar_year": 2024}
        )


# Captured from the original Data handovers before canonicalizing IDs and names.
# Preserve all physical layer/glazing fields and numeric role metrics; curation
# metadata and generated material names do not determine the physical model.
_HANDOFF_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/archetype-consumer-baseline.json").read_text()
)
HANDOFF_BASELINES = _HANDOFF_FIXTURE["configurations"]


def construction_physics(record):
    """Retain every physical construction value while ignoring display identity."""
    result = json.loads(json.dumps(record))
    if "layers" in result:
        for layer in result["layers"]:
            layer["material"].pop("name", None)
    return normalized_physical_values(result)


@pytest.mark.parametrize("key", HANDOFF_BASELINES)
def test_nominal_handoff_uses_common_authoring_without_calibration_dependency(
    key, monkeypatch
):
    from importlib import import_module

    import epsm.catalogue_release as release

    def denied(*args, **kwargs):
        pytest.fail(
            "Physical composition must not require target/calibration acceptance"
        )

    get, metadata, export = (
        Catalogue.get,
        Catalogue.nominal_metadata,
        release.export_nominal_constructions,
    )
    selected, described, exported = [], [], []

    def select(self, identifier, *, state=None, ventilation=None):
        result = get(self, identifier, state=state, ventilation=ventilation)
        selected.append((identifier, state, result))
        return result

    def describe(self, identifier, *, state=None):
        result = metadata(self, identifier, state=state)
        described.append((identifier, state, result))
        return result

    def handover(archetype, *, metadata):
        exported.append((archetype, metadata))
        return export(archetype, metadata=metadata)

    monkeypatch.setattr(Catalogue, "get", select)
    monkeypatch.setattr(Catalogue, "nominal_metadata", describe)
    monkeypatch.setattr(Catalogue, "assess", denied, raising=False)
    monkeypatch.setattr(release, "export_nominal_constructions", handover)
    # Transitional public names may disappear after the installed migration gate.
    # The consumer assertion uses only current public boundaries, never private helpers.
    try:
        layered = import_module("epsm_data.layered")
    except ModuleNotFoundError:
        layered = None
    if layered is not None and hasattr(layered, "load_calibrated_archetype"):
        monkeypatch.setattr(layered, "load_calibrated_archetype", denied)
    aid, state = key.split(":")
    state = None if state == "None" else state
    result = release.core_inputs(aid, state)
    assert [(identifier, choice) for identifier, choice, _ in selected] == [
        (aid, state)
    ]
    assert [(identifier, choice) for identifier, choice, _ in described] == [
        (aid, state)
    ]
    assert len(exported) == 1
    assert exported[0][0] is selected[0][2] is result["archetype"]
    assert exported[0][1] is described[0][2]
    expected = HANDOFF_BASELINES[key]
    actual = result["nominal_bundle"]
    assert {
        role: construction_physics(record) for role, record in actual["core"].items()
    } == normalized_physical_values(expected["core"])
    assert {
        role: {field: normalized_physical_values(record[field]) for field in metrics}
        for role, metrics in expected["roles"].items()
        for record in (actual["roles"][role],)
    } == normalized_physical_values(expected["roles"])
    top_role = "TOP_FLOOR" if "TOP_FLOOR" in expected["core"] else "ROOF"
    for field, role in {
        "wall": "EXT_WALL",
        "top": top_role,
        "ground": "GROUND_FLOOR",
        "intermediate_floor": "INTERMEDIATE_FLOOR",
        "basement_wall": "BASEMENT_WALL",
    }.items():
        assert construction_physics(
            getattr(result["envelope"], field).model_dump(mode="json")
        ) == normalized_physical_values(expected["core"][role])
    assert construction_physics(
        result["envelope"].weather_shell.model_dump(mode="json")
    ) == normalized_physical_values(_HANDOFF_FIXTURE["weather_shell"])
    for field, value in expected["core"]["WINDOW"].items():
        assert getattr(result["glazing"], field) == value


def test_independent_component_evidence_builds_portable_archetype_without_cross_changes():
    from epsm_data.domain import BuildingElement as Role

    from epsm.catalogue_application import resolve_building_archetype

    options = dict(
        category="multi_family",
        construction_year=1960,
        climate_zone="SE.Zone3",
        ventilation="F",
        default_state="existing",
        tabula_reference_area_m2=125,
        conditioned_volume_m3=480,
    )
    original = resolve_building_archetype(**options)
    selected = resolve_building_archetype(
        **options,
        component_states={"window": "advanced"},
        component_sources={"window": "survey:window-installation"},
    )
    old, new = original["archetype"], selected["archetype"]
    assert (
        new.construction_set.elements[Role.WINDOW]
        != old.construction_set.elements[Role.WINDOW]
    )
    assert (
        new.construction_set.elements[Role.EXT_WALL]
        == old.construction_set.elements[Role.EXT_WALL]
    )
    assert selected["core_airflow_inputs"] == original["core_airflow_inputs"]
    assert new.envelope_performance == old.envelope_performance
    assert any("survey:window-installation" in ref for ref in new.source_references)
    assert (
        selected["assignment"]["components"]["window"]["status"]
        == "evidence_selected_catalogue_representative"
    )
    assert selected["assignment"]["components"]["airtightness"]["status"] == "assumed"
    with pytest.raises(ValueError, match="independent source"):
        resolve_building_archetype(**options, component_states={"window": "advanced"})
    with pytest.raises(ValueError, match="Unknown component"):
        resolve_building_archetype(
            **options, component_states={"best_heating_error": "advanced"}
        )


def _legacy_record(year=1977):
    from datetime import date

    from sweden_ubem.enums import BuildingType
    from sweden_ubem.records import BuildingRecord

    footprint = box(0, 0, 10, 10)
    certificate = "synthetic-certificate"
    observations = tuple(
        dict(
            certificate_id=certificate,
            source_field=key,
            raw_values=[str(value)],
            mapping_status="verified",
        )
        for key, value in {
            "EgenAtemp": 90,
            "EgenAntalPlan": 1,
            "EgenAntalKallarplan": 0,
            "EgenNybyggAr": year,
            "EgenAtempBostad": 100,
        }.items()
    )
    record = BuildingRecord(
        "synthetic-release",
        "building-one",
        BuildingType("multi_family"),
        footprint,
        facts=dict(
            geometry_status="resolved",
            construction_year=year,
            status_verified=True,
            is_existing=True,
        ),
        components=(
            dict(
                component_id="one",
                geometry_hash="hash",
                geometry=footprint,
                outline_labels=["Fasad"],
            ),
        ),
        heights=(
            dict(
                component_id="one",
                input_geometry_hash="hash",
                height_status="determined",
                roof_form="flat",
                representative_height_m=3,
                eave_height_m=3,
                details={"evidence_resolution": "resolved"},
            ),
        ),
        certificates=(
            dict(
                certificate_id=certificate,
                certificate_date=date(2023, 1, 1),
                date_status="verified",
                subject_count=1,
                loaded_building_count=1,
                matching_status="fully_matched",
            ),
        ),
        observations=observations,
    )
    return record


def test_legacy_record_handoff_preserves_area_evidence_and_portable_definition(
    tmp_path,
):
    pytest.importorskip("sweden_ubem")
    from importlib.resources import files

    from sweden_ubem.weather import WeatherReference

    from epsm.legacy_records import EPSMBuilding

    record = _legacy_record()
    before = record.to_dict()
    weather = WeatherReference.from_epw(
        files("epsm_rc") / "data/epw/goteborg.epw", calendar_year=2023
    )
    result, receipt = EPSMBuilding.from_record(
        record,
        weather=weather,
        preflight=False,
        overrides={
            "component_states": {"window": "advanced"},
            "component_sources": {"window": "synthetic:window-survey"},
        },
    )
    assert result.spec.load_reference_area_m2 == 90
    assert result.spec.geometry.conditioned_floor_area_m2 == 100
    assert result.spec.use.dhw_kwh_m2_year == 25
    assert receipt.identities["load_to_physical_area_ratio"] == 0.9
    assert receipt.identities["archetype_definition"]["format_version"] == 4
    assert (
        receipt.identities["archetype_assignment"]["components"]["window"]["source"]
        == "synthetic:window-survey"
    )
    assert (
        receipt.identities["archetype_assignment"]["components"]["airtightness"][
            "state"
        ]
        == "existing"
    )
    assert record.to_dict() == before and not receipt.ready_for_simulation
    paths = result.write(tmp_path / "model.json")
    assert all(path.exists() for path in paths)
    assert (
        json.loads(paths[1].read_text())["identities"]["archetype_definition"]
        == receipt.identities["archetype_definition"]
    )


def test_legacy_record_handoff_runs_se07_without_renovation_state():
    pytest.importorskip("sweden_ubem")
    from importlib.resources import files

    from sweden_ubem.weather import WeatherReference

    from epsm.legacy_records import EPSMBuilding, ModelAssemblyError

    weather = WeatherReference.from_epw(
        files("epsm_rc") / "data/epw/goteborg.epw", calendar_year=2023
    )
    record = _legacy_record(2023)
    _, receipt = EPSMBuilding.from_record(record, weather=weather, preflight=False)
    assert receipt.identities["archetype_assignment"]["era"] == "SE.07"
    with pytest.raises(ModelAssemblyError, match="SE.07 has one catalogue configuration"):
        EPSMBuilding.from_record(
            record, weather=weather, preflight=False, overrides={"renovation_state": "existing"}
        )
    _, older = EPSMBuilding.from_record(_legacy_record(), weather=weather, preflight=False)
    assert older.identities["archetype_assignment"]["components"]["wall"]["state"] == "existing"


def _lake_record(record):
    """The same evidence as a GIS-lake (epsm_db schema 2) record."""
    from dataclasses import replace

    facts = dict(
        construction_year=record.facts["construction_year"],
        geometry_valid=True,
        object_status="Gällande",
    )
    components = tuple(
        dict(
            {k: v for k, v in c.items() if k not in {"geometry_hash", "outline_labels"}},
            attributes={"outline_labels": c["outline_labels"]},
        )
        for c in record.components
    )
    heights = tuple(
        dict(
            {k: v for k, v in h.items() if k not in {"input_geometry_hash", "details"}},
            attributes={"geometry_status": "consistent_source_component"},
        )
        for h in record.heights
    )
    return replace(record, facts=facts, components=components, heights=heights)


def test_legacy_record_handoff_reads_gis_lake_evidence():
    pytest.importorskip("sweden_ubem")
    from dataclasses import replace
    from importlib.resources import files

    from sweden_ubem.weather import WeatherReference

    from epsm.legacy_records import EPSMBuilding, ModelAssemblyError

    weather = WeatherReference.from_epw(
        files("epsm_rc") / "data/epw/goteborg.epw", calendar_year=2023
    )
    record = _legacy_record()
    lake = _lake_record(record)
    legacy, _ = EPSMBuilding.from_record(record, weather=weather, preflight=False)
    built, _ = EPSMBuilding.from_record(lake, weather=weather, preflight=False)
    assert built.spec.physical_hash() == legacy.spec.physical_hash()
    for facts, heights, message in (
        ({**lake.facts, "object_status": "Avregistrerad"}, lake.heights, "existing-building"),
        (lake.facts, tuple(
            dict(h, attributes={"geometry_status": "unresolved_roof_evidence"}) for h in lake.heights
        ), "Unresolved height"),
    ):
        with pytest.raises(ModelAssemblyError, match=message):
            EPSMBuilding.from_record(
                replace(lake, facts=facts, heights=heights), weather=weather, preflight=False
            )


def test_missing_basement_recipe_requires_explicit_input_without_floor_substitution(
    monkeypatch,
):
    import epsm.catalogue_release as release

    export = release.export_nominal_constructions

    def without_basement(*args, **kwargs):
        bundle = export(*args, **kwargs)
        bundle["core"].pop("BASEMENT_WALL", None)
        return bundle

    monkeypatch.setattr(release, "export_nominal_constructions", without_basement)
    with pytest.raises(ValueError, match="explicit basement_wall"):
        release.core_inputs("school_se05")


def test_compact_roof_component_selection_keeps_its_original_physical_role():
    from epsm_data.domain import BuildingElement as Role

    from epsm.catalogue_application import resolve_building_archetype

    selected = resolve_building_archetype(
        category="office",
        construction_year=1990,
        climate_zone="SE.Zone3",
        ventilation="FTX",
        default_state="existing",
        component_states={"roof": "advanced"},
        component_sources={"roof": "survey:roof"},
    )
    elements = selected["archetype"].construction_set.elements
    assert Role.ROOF in elements and Role.TOP_FLOOR not in elements
    expected = Catalogue.load().for_year("office", 1990, state="advanced")
    assert elements[Role.ROOF] == expected.construction_set.elements[Role.ROOF]


def test_component_composition_gets_new_snapshot_identity_only_when_fabric_changes():
    from epsm.catalogue_application import resolve_building_archetype

    options = dict(
        category="multi_family",
        construction_year=1960,
        climate_zone="SE.Zone3",
        ventilation="F",
        default_state="existing",
    )
    base = Catalogue.load().for_year("multi_family", 1960)
    unchanged = resolve_building_archetype(
        **options,
        component_states={"window": "existing"},
        component_sources={"window": "survey:original-window"},
    )["archetype"].construction_set
    mixed = resolve_building_archetype(
        **options,
        component_states={"window": "advanced"},
        component_sources={"window": "survey:replacement-window"},
    )["archetype"].construction_set
    assert unchanged.version_id == base.construction_set.version_id
    assert mixed.version_id != base.construction_set.version_id
    assert mixed.valid_from_year is None


@pytest.mark.parametrize("key", HANDOFF_BASELINES)
def test_nominal_handoff_preservation_under_python_311_summation(key, monkeypatch):
    import epsm_data.nominal as nominal

    def historical_sum(items, start=0):
        result = start
        for item in items:
            result += item
        return result

    monkeypatch.setattr(nominal, "sum", historical_sum, raising=False)
    test_nominal_handoff_uses_common_authoring_without_calibration_dependency(
        key, monkeypatch
    )


def test_catalogue_selection_keeps_caller_case_context(caplog):
    import logging

    from epsm.catalogue_application import resolve_building_archetype

    with caplog.at_level(logging.DEBUG):
        selected = resolve_building_archetype(
            category="multi_family",
            construction_year=1960,
            climate_zone="SE.Zone3",
            ventilation="F",
            default_state="existing",
            log_context={"case_id": "archetype-selection-case"},
        )
    events = [
        record
        for record in caplog.records
        if record.name == "epsm_data.catalogue"
        and getattr(record, "epsm_event", "") == "catalogue.select.started"
    ]
    assert events
    assert all(
        record.epsm_context.get("case_id") == "archetype-selection-case"
        for record in events
    )
    assert selected["assignment"]["category"] == "multi_family"
