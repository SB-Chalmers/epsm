"""Measured stock operation is an explicit choice, applied on both record routes."""

from types import SimpleNamespace

import pytest
from epsm_core import Footprint, GeometrySpec
from epsm_db.records import Receipt

from epsm import Building
from epsm._programme_airflow import measured_air_change
from epsm.catalogue_application import resolve_building_archetype
from epsm.legacy_records import ModelPolicy, _delivery, _operation

MEASURED = ModelPolicy(operating_standard="measured")
INFILTRATION = {"envelope_infiltration_ach": 0.1}


def operation(name, policy, *, ventilation="S", era="SE.02", residential_type="multi_family"):
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 10), storeys=2, storey_height_m=3
    )
    receipt = Receipt("test")
    use, air, source = _operation(
        name, 2023, ventilation=ventilation, infiltration=INFILTRATION, geometry=geometry,
        area=180, policy=policy, receipt=receipt, era=era, residential_type=residential_type,
    )
    return use, air, source, receipt


def test_normal_use_stays_the_default():
    assert ModelPolicy().operating_standard == "sveby"
    with pytest.raises(ValueError, match="operating_standard"):
        ModelPolicy(operating_standard="fitted")


@pytest.mark.parametrize(("era", "setpoint"), [("SE.01", 22.2), ("SE.03", 22.5), ("SE.07", 23.0)])
def test_measured_multifamily_setpoint_follows_the_era(era, setpoint):
    use, *_ = operation("residential", MEASURED, ventilation="F", era=era)
    assert set(use.heating_setpoint.hourly(2023)) == {setpoint}


def test_measured_total_is_net_of_this_buildings_infiltration():
    _, air, _, receipt = operation("residential", MEASURED)
    assert air.natural_exchange_ach == pytest.approx(0.39 - 0.1)
    assert any("0.39 ACH" in note for note in receipt.assumptions)


def test_normal_use_keeps_its_flow_based_exchange():
    _, air, _, _ = operation("residential", ModelPolicy())
    assert air.natural_exchange_ach != pytest.approx(0.29)


def test_mechanical_systems_have_no_measured_total():
    _, air, _, _ = operation("residential", MEASURED, ventilation="F")
    assert air.natural_exchange_ach == 0


def test_uses_without_an_adopted_value_keep_normal_use_and_say_so():
    measured = operation("residential", MEASURED, residential_type="single_family")
    normal = operation("residential", ModelPolicy(), residential_type="single_family")
    assert measured[0] == normal[0] and measured[1] == normal[1]
    assert any("no value adopted" in note for note in measured[3].assumptions)


def test_measured_office_flow_and_hours():
    _, measured, _, _ = operation("office", MEASURED, ventilation="F")
    _, normal, _, _ = operation("office", ModelPolicy(), ventilation="F")
    assert measured.mechanical_vent_l_s_m2 == pytest.approx(1.6)
    assert measured.mechanical_vent_fraction != normal.mechanical_vent_fraction


def test_a_mixed_building_nets_only_the_use_with_a_total():
    _, office, _, _ = operation("office", MEASURED)
    assert office.natural_exchange_ach == pytest.approx(1.6 * 180 * 3.6 / 600)


def systems(carriers):
    return SimpleNamespace(
        heating_carrier=carriers[0] if len(carriers) == 1 else None, heating_carriers=carriers
    )


@pytest.mark.parametrize(
    ("carrier", "cop"), [("heat_pump", 2.75), ("district_heat", None)]
)
def test_delivery_takes_the_heat_pump_cop_from_data(monkeypatch, carrier, cop):
    monkeypatch.setattr(
        "epsm.legacy_records._observed_systems", lambda record: systems([carrier])
    )
    receipt = Receipt("test")
    heating = _delivery(None, ModelPolicy(), receipt).heating
    assert heating.carrier == carrier
    if cop is None:
        assert heating.heat_pump_cop is None
        assert "heating_delivery_template" not in receipt.identities
    else:
        assert set(heating.heat_pump_cop.hourly(2023)) == {cop}
        assert receipt.identities["heating_delivery_template"] == (
            "epsm.heating.heat_pump_field_average"
        )


@pytest.mark.parametrize("observed", [None, systems(["heat_pump", "fuel"])])
def test_mixed_or_unknown_carriers_report_ideal_demand(monkeypatch, observed):
    monkeypatch.setattr("epsm.legacy_records._observed_systems", lambda record: observed)
    receipt = Receipt("test")
    assert _delivery(None, ModelPolicy(), receipt).heating is None
    assert receipt.quality


def selection(**options):
    return resolve_building_archetype(
        construction_year=1930, climate_zone="SE.Zone3", ventilation="S", **options
    )["archetype"]


def test_catalogue_selection_keeps_normal_use_unless_asked():
    assert (
        selection(category="multi_family").operating_profile
        == resolve_building_archetype(
            category="multi_family", construction_year=1930, climate_zone="SE.Zone3",
            ventilation="S", operating_standard="sveby",
        )["archetype"].operating_profile
    )
    with pytest.raises(ValueError, match="operating_standard"):
        selection(category="multi_family", operating_standard="fitted")


def test_catalogue_selection_carries_the_measured_profile():
    profile = selection(category="multi_family", operating_standard="measured").operating_profile
    assert profile.profile_id == "epsm.measured_use.v1.multi_family.SE.01"
    assert measured_air_change(profile, "S") == 0.39
    assert measured_air_change(profile, "F") is None


def test_generic_borrows_the_multifamily_measured_profile():
    profile = selection(category="generic", operating_standard="measured").operating_profile
    assert profile.profile_id == "epsm.measured_use.v1.multi_family.SE.01"


def test_apply_archetype_nets_the_measured_total():
    building = Building.from_footprint(
        Footprint.rectangle(10, 10), storeys=2, storey_height_m=3,
        identifier="b", load_reference_area_m2=180,
    )
    archetype = selection(category="multi_family", operating_standard="measured")
    building.apply_archetype(archetype, calendar={"calendar_year": 2023})
    airflow = building.hvac.airflow
    volume = building.geometry.conditioned_volume_m3
    infiltration = (
        airflow.infiltration_design_flow_m3_s(reference_area_m2=180, volume_m3=volume)
        * 3600 / volume
    )
    assert airflow.natural_exchange_ach == pytest.approx(max(0.39 - infiltration, 0.05))
    assert [
        r.assumption_profile
        for r in building.provenance.records
        if r.field_path == "hvac.airflow.natural_exchange_ach"
    ] == [archetype.operating_profile.profile_id]


def test_apply_archetype_without_geometry_reports_the_requirement():
    building = Building.empty(identifier="b", load_reference_area_m2=180)
    archetype = selection(category="multi_family", operating_standard="measured")
    building.apply_archetype(
        archetype.with_changes(construction_set=None), calendar={"calendar_year": 2023}
    )
    assert (
        "operating_profile.measured_use.total_air_change_ach (geometry)"
        in building.archetype_applications[-1].requirements
    )
