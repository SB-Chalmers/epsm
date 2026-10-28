"""Catalogue and authored definitions use one atomic geometry-preserving route."""

# ruff: noqa: F811

import json

import pytest
from epsm_core import SourceRecord
from epsm_data import (
    Archetype,
    ConstructionSet,
    EnvelopePerformance,
    HVACTemplate,
    OperatingProfile,
)
from epsm_data.domain import BuildingElement as Role
from test_platform import engine, reference, replacement, weather  # noqa: F401

from epsm import Building


def authored(**sections):
    return Archetype(
        "research.custom",
        "Authored example",
        source_references=("study:example",),
        **sections,
    )


def use_profile(building, **changes):
    values = building.operation.with_changes(**changes).model_dump(mode="json")
    return OperatingProfile(
        "study:use", {"building_assumptions": {"use": values}}, ("study:programme",)
    )


def test_replace_preserves_geometry_openings_and_uncovered_assignments():
    b = reference()
    before = b.snapshot().to_dict()
    window = b.construction_set.elements[Role.WINDOW].with_changes(u_value=0.9)
    report = b.apply_archetype(
        authored(
            construction_set=ConstructionSet(elements={Role.WINDOW: window}),
            operating_profile=use_profile(b, equipment_gain_w_m2=8),
        )
    )
    assert report.archetype_id == "research.custom"
    assert "operation" in report.replaced
    after = b.snapshot().to_dict()
    for key in ("geometry", "facade", "context", "foundation", "ground_temperature"):
        assert after[key] == before[key]
    for old, new in zip(before["elements"], after["elements"]):
        if old["role"] != Role.WINDOW.value:
            assert old == new
        else:
            for key in ("identifier", "area_m2", "facade_id", "storey", "elevation_m"):
                assert old[key] == new[key]
    assert b.operation.equipment_gain_w_m2 == 8
    assert all(
        e.construction.u_value == 0.9 for e in b.elements if e.role == Role.WINDOW
    )
    assert b.hvac.to_dict() == before["hvac"]


def test_fill_retains_effective_choices_and_ignores_unused_calendar_requirement():
    from epsm_data import select_operating_profile

    b = reference()
    before = b.snapshot()
    report = b.apply_archetype(
        authored(operating_profile=select_operating_profile("office")),
        mode="fill_missing",
    )
    assert b.snapshot().sha256 == before.sha256
    assert "operation" in report.retained
    assert not any("calendar" in x for x in report.requirements)


@pytest.mark.parametrize(
    "values",
    [
        {"use": {"equipment_gain_w_m2": -1}},
        {"use": {"heating_setpoint_c": 25, "cooling_setpoint_c": 20}},
        {
            "airflow": {
                "envelope_infiltration_ach": 1,
                "envelope_infiltration_l_s_m2": 1,
            }
        },
    ],
)
def test_invalid_profile_rolls_back_all_inputs_even_when_fill_would_retain(values):
    b = reference()
    before = b.to_dict()
    bad = OperatingProfile("invalid", {"building_assumptions": values})
    with pytest.raises(ValueError):
        b.apply_archetype(
            authored(construction_set=b.construction_set, operating_profile=bad),
            mode="fill_missing",
        )
    assert b.to_dict() == before


@pytest.mark.parametrize(
    "section",
    [
        {"delivery": {"heating": {"carrier": "electricity", "efficiency": -1}}},
        {"equipment": [{"identifier": "bad", "product_id": "bad", "count": -1}]},
        {"renewables": {"pv_systems": [{"dc_capacity_kw": -1}]}},
    ],
)
def test_invalid_template_is_rejected_even_when_airflow_is_incomplete(section):
    b = Building()
    before = b.to_dict()
    with pytest.raises(ValueError):
        b.apply_archetype(
            authored(
                hvac_template=HVACTemplate(
                    "bad", {"airflow": {"topology": "F"}, **section}
                )
            )
        )
    assert b.to_dict() == before


def test_envelope_patch_preserves_installed_delivery_equipment_and_sources():
    b = reference()
    b.provenance = b.provenance.updated(
        records=(
            *b.provenance.records,
            SourceRecord(
                field_path="hvac.delivery", status="measured", source="plant:survey"
            ),
        )
    )
    old = b.hvac.to_dict()
    b.apply_archetype(
        authored(
            envelope_performance=EnvelopePerformance(
                infiltration_ach=0.2,
                infiltration_reference_basis="conditioned_volume",
                source_references=("study:leakage",),
            )
        )
    )
    assert b.hvac.airflow.envelope_infiltration_ach == 0.2
    for field in ("delivery", "equipment", "renewables"):
        assert b.hvac.to_dict()[field] == old[field]
    assert any(
        r.field_path == "hvac.delivery" and r.source == "plant:survey"
        for r in b.provenance.records
    )


def test_operation_profile_patches_ventilation_without_selecting_a_system():
    b = reference()
    old = b.hvac.to_dict()
    profile = OperatingProfile(
        "study:airflow",
        {"building_assumptions": {"airflow": {"mechanical_vent_l_s_m2": 0.7}}},
    )
    b.apply_archetype(authored(operating_profile=profile))
    assert b.hvac.airflow.mechanical_vent_l_s_m2 == 0.7
    assert b.hvac.delivery.model_dump(mode="json") == old["delivery"]
    empty = Building()
    report = empty.apply_archetype(authored(operating_profile=profile))
    assert empty.hvac is None
    assert "airflow_properties" in report.unmatched
    assert any("hvac" in value for value in report.requirements)


def test_fill_keeps_explicit_zero_and_fills_independent_bridge():
    b = reference()
    b.hvac = b.hvac.with_changes(
        airflow=b.hvac.airflow.updated(
            envelope_infiltration_ach=0, envelope_infiltration_l_s_m2=None
        )
    )
    b.thermal_bridge_uplift_fraction = None
    report = b.apply_archetype(
        authored(
            envelope_performance=EnvelopePerformance(
                infiltration_ach=0.2,
                infiltration_reference_basis="conditioned_volume",
                thermal_bridge_uplift_fraction=0.1,
            )
        ),
        mode="fill_missing",
    )
    assert b.hvac.airflow.envelope_infiltration_ach == 0
    assert b.thermal_bridge_uplift_fraction == 0.1
    assert "hvac.airflow.envelope_infiltration_ach" in report.retained


def test_source_reference_volume_is_unresolved_without_conversion():
    b = reference()
    before = b.hvac.to_dict()
    report = b.apply_archetype(
        authored(
            envelope_performance=EnvelopePerformance(
                infiltration_ach=0.2,
                infiltration_reference_basis="tabula_reference_volume",
            )
        )
    )
    assert b.hvac.to_dict() == before
    assert any("reference_volume" in value for value in report.requirements)


def test_atemp_basis_requires_explicit_area_and_records_interpretation():
    envelope = EnvelopePerformance(
        infiltration_l_s_m2=0.1, infiltration_reference_basis="Atemp"
    )
    b = reference()
    b.load_reference_area_m2 = None
    b.load_reference_area_policy = "conditioned_floor_area"
    before = b.hvac.to_dict()
    unresolved = b.apply_archetype(authored(envelope_performance=envelope))
    assert b.hvac.to_dict() == before
    assert any("Atemp" in value for value in unresolved.requirements)
    b.load_reference_area_policy = None
    b.load_reference_area_m2 = 120
    report = b.apply_archetype(authored(envelope_performance=envelope))
    assert b.hvac.airflow.envelope_infiltration_l_s_m2 == 0.1
    assert any("Atemp" in str(item) for item in report.assumptions)
    assert b.load_reference_area_m2 == 120


def test_conflicting_reference_area_evidence_stays_unresolved():
    b = reference()
    b.load_reference_area_m2 = 120
    b.provenance = b.provenance.updated(
        records=(
            *b.provenance.records,
            SourceRecord(
                field_path="load_reference_area_m2",
                status="measured",
                source="survey",
                evidence={"reference_basis": "gross_floor_area"},
            ),
        )
    )
    before = b.hvac.to_dict()
    report = b.apply_archetype(
        authored(
            envelope_performance=EnvelopePerformance(
                infiltration_l_s_m2=0.1, infiltration_reference_basis="Atemp"
            )
        )
    )
    assert b.hvac.to_dict() == before
    assert any("Atemp" in value for value in report.requirements)


def test_reports_survive_save_copy_and_renovation_without_mutation(tmp_path):
    b = reference()
    report = b.apply_archetype(
        authored(operating_profile=use_profile(b, equipment_gain_w_m2=8))
    )
    expected = report.to_dict()
    exported = report.to_dict()
    exported["definition"]["archetype"]["notes"].append("changed export")
    assert report.to_dict() == expected
    assert len(repr(report)) < 200
    for child in (
        b.copy(),
        Building.from_dict(json.loads(json.dumps(b.to_dict()))),
        b.renovate(replacement(b)),
    ):
        assert child.archetype_applications[0].to_dict() == expected
        child.apply_archetype(authored())
        assert len(child.archetype_applications) == 2
    assert len(b.archetype_applications) == 1
    path = tmp_path / "building.json"
    path.write_text(json.dumps(b.to_dict()))
    assert (
        Building.from_dict(json.loads(path.read_text()))
        .archetype_applications[0]
        .to_dict()
        == expected
    )
    old = b.to_dict()
    old.pop("archetype_applications")
    assert Building.from_dict(old).archetype_applications == ()


def test_evaluation_keeps_application_history_before_later_application(
    tmp_path, weather, engine
):
    b = reference()
    first = b.apply_archetype(authored())
    evaluation = b.simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
    before = evaluation.to_dict()
    b.apply_archetype(authored(operating_profile=use_profile(b, equipment_gain_w_m2=8)))
    assert evaluation.to_dict() == before
    assert evaluation.archetype_applications == [first.to_dict()]


def test_partial_profile_preserves_sources_of_unmodified_operation_fields():
    b = reference()
    b.provenance = b.provenance.updated(
        records=(
            *b.provenance.records,
            SourceRecord(
                field_path="operation", status="measured", source="use:survey"
            ),
        )
    )
    profile = OperatingProfile(
        "study:partial",
        {"building_assumptions": {"use": {"equipment_gain_w_m2": 8}}},
        ("study:equipment",),
    )
    b.apply_archetype(authored(operating_profile=profile))
    records = {r.field_path: r for r in b.provenance.records}
    assert records["operation.equipment_gain_w_m2"].source == "study:equipment"
    assert records["operation.heating_setpoint.values.0"].source == "use:survey"


def test_empty_template_does_not_claim_existing_system_evidence():
    b = reference()
    before = b.snapshot()
    report = b.apply_archetype(authored(hvac_template=HVACTemplate("empty", {})))
    assert b.snapshot().sha256 == before.sha256
    assert "hvac" not in report.replaced


def test_same_call_airflow_sources_follow_explicit_precedence():
    b = reference()
    profile = OperatingProfile(
        "programme",
        {"building_assumptions": {"airflow": {"mechanical_vent_l_s_m2": 0.3}}},
        ("source:programme",),
    )
    template = HVACTemplate(
        "chosen",
        {"airflow": {"mechanical_vent_l_s_m2": 0.7, "envelope_infiltration_ach": 0.4}},
        ("source:template",),
    )
    envelope = EnvelopePerformance(
        infiltration_ach=0.2,
        infiltration_reference_basis="conditioned_volume",
        source_references=("source:envelope",),
    )
    b.apply_archetype(
        authored(
            operating_profile=profile,
            hvac_template=template,
            envelope_performance=envelope,
        )
    )
    records = {r.field_path: r for r in b.provenance.records}
    assert records["hvac.airflow.mechanical_vent_l_s_m2"].source == "source:template"
    assert records["hvac.airflow.envelope_infiltration_ach"].source == "source:envelope"
    assert not any(r.field_path == "hvac.airflow" for r in b.provenance.records)


def test_catalogue_and_authored_archetypes_enter_the_same_assignment_route(monkeypatch):
    from epsm_data import Catalogue

    selected = Catalogue.load().get("mf_se02", state="existing")
    custom = authored(construction_set=selected.construction_set)
    observed = []
    assign = Building.assign_inputs

    def track(self, **inputs):
        observed.append(inputs["construction_set"])
        return assign(self, **inputs)

    monkeypatch.setattr(Building, "assign_inputs", track)
    for archetype in (selected, custom):
        b = reference()
        report = b.apply_archetype(archetype)
        assert report.applied or report.replaced
        assert b.archetype_applications == (report,)
    assert observed == [selected.construction_set, selected.construction_set]


def test_incomplete_authoring_on_geometry_is_partial_without_system_guesses():
    from epsm_core import Footprint

    b = Building.from_footprint(
        Footprint.rectangle(12, 8), storeys=2, storey_height_m=2.8
    )
    geometry = b.geometry
    report = b.apply_archetype(
        authored(
            hvac_template=HVACTemplate("chosen-partial", {"airflow": {"topology": "F"}})
        )
    )
    assert b.geometry == geometry
    assert b.hvac is None and b.facade is None and b.operation is None
    assert any("infiltration" in value for value in report.requirements)
    assert "hvac" in report.requirements
    assert b.archetype_applications == (report,)


def test_template_equipment_patch_preserves_identity_and_sources_by_resolved_order():
    from epsm_core import Equipment

    b = reference()
    b.hvac = b.hvac.with_changes(
        equipment=(Equipment("first", "one"), Equipment("second", "two"))
    )
    original = b.hvac.equipment
    b.provenance = b.provenance.updated(
        records=(
            *b.provenance.records,
            SourceRecord(field_path="hvac", status="measured", source="plant:survey"),
        )
    )
    b.apply_archetype(
        authored(
            hvac_template=HVACTemplate(
                "count",
                {"equipment": [{"identifier": "second", "count": 3}]},
                ("source:count",),
            )
        )
    )
    assert b.hvac.equipment[0] == original[0]
    assert b.hvac.equipment[1].occurrence_id == original[1].occurrence_id
    assert b.hvac.equipment[1].count == 3
    records = {r.field_path: r for r in b.provenance.records}
    assert records["hvac.equipment.0.count"].source == "plant:survey"
    assert records["hvac.equipment.1.count"].source == "source:count"
    assert records["hvac.equipment.1.product_id"].source == "plant:survey"


def test_nested_airflow_schedule_sources_follow_template_precedence():
    from epsm_data import load_operating_profile

    b = reference()
    template = HVACTemplate(
        "clock",
        {"airflow": {"mechanical_vent_fraction": {"values": [0.5] * 24}}},
        ("source:chosen-clock",),
    )
    b.apply_archetype(
        authored(
            operating_profile=load_operating_profile("generic_other"),
            hvac_template=template,
        )
    )
    assert set(b.hvac.airflow.mechanical_vent_fraction.all_values) == {0.5}
    records = [
        record
        for record in b.provenance.records
        if record.field_path == "hvac.airflow.mechanical_vent_fraction"
        or record.field_path.startswith("hvac.airflow.mechanical_vent_fraction.")
    ]
    assert records
    assert {record.source for record in records} == {"source:chosen-clock"}
    assert len({record.field_path for record in records}) == len(records)


def test_template_schedule_replacement_discards_stale_calendar_sources():
    from epsm_core import ScheduleSpec

    b = reference()
    b.hvac = b.hvac.with_changes(
        airflow=b.hvac.airflow.updated(
            mechanical_vent_fraction=ScheduleSpec(
                values=(1.0,) * 24, weekday_values=((0.8,) * 24,) * 7
            )
        )
    )
    b.provenance = b.provenance.updated(
        records=(
            *b.provenance.records,
            SourceRecord(
                field_path="hvac.airflow.mechanical_vent_fraction",
                status="measured",
                source="old-clock",
            ),
        )
    )
    template = HVACTemplate(
        "replacement-clock",
        {"airflow": {"mechanical_vent_fraction": {"values": [0.5] * 24}}},
        ("replacement-clock",),
    )
    b.apply_archetype(authored(hvac_template=template))
    assert b.hvac.airflow.mechanical_vent_fraction.weekday_values is None
    assert not any(
        r.field_path.startswith("hvac.airflow.mechanical_vent_fraction.weekday_values")
        for r in b.provenance.records
    )


def test_applied_bridge_surcharge_replaces_the_uplift_fraction():
    b = reference()
    b.apply_archetype(authored(envelope_performance=EnvelopePerformance(
        thermal_bridge_delta_u_w_m2k=0.1, source_references=("study:tabula",))))
    assert b.thermal_bridge_delta_u_w_m2k == 0.1
    assert b.thermal_bridge_uplift_fraction is None
    assert any(r.field_path == "thermal_bridge_delta_u_w_m2k" for r in b.provenance.records)
    b.apply_archetype(authored(envelope_performance=EnvelopePerformance(
        thermal_bridge_uplift_fraction=0.05, source_references=("study:uplift",))))
    assert b.thermal_bridge_uplift_fraction == 0.05
    assert b.thermal_bridge_delta_u_w_m2k is None
