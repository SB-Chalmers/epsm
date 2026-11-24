"""Heat-pump COP by EPC pump type and era (policy version 6), with synthetic inputs only."""

from types import SimpleNamespace

import pytest
from epsm_db.records import Receipt

from epsm.legacy_records import ModelPolicy, _delivery

COP = {"ground": 2.75, "exhaust_air": {"SE.05": 2.4, "SE.06": 2.75}, "air_water": 2.4, "air_air": 2.0}


def typed_template(carrier="heat_pump", *, heat_pump_type=None, era=None):
    """Stand-in for Data's typed template: same shape, synthetic values."""
    cop, template_id = 2.75, "epsm.heating.heat_pump_field_average"
    if heat_pump_type is not None:
        value = COP[heat_pump_type]
        if isinstance(value, dict):
            value = value.get(era)
        if value is not None:
            cop, template_id = value, f"epsm.heating.heat_pump_{heat_pump_type}"
    return SimpleNamespace(template_id=template_id, values={"delivery": {"heating": {
        "carrier": carrier, "heat_pump_cop": {"values": [cop] * 24}, "source": template_id}}})


def untyped_template(carrier="heat_pump"):
    """Stand-in for a Data release without COP by pump type."""
    return typed_template(carrier)


def heat_pump(pump_type):
    return SimpleNamespace(heating_carrier="heat_pump", heating_carriers=["heat_pump"], heat_pump_type=pump_type)


@pytest.fixture
def typed(monkeypatch):
    monkeypatch.setattr("epsm_data.templates.heating_delivery_template", typed_template)


@pytest.mark.parametrize(("pump_type", "era", "cop"), [
    ("ground", "SE.03", 2.75), ("air_water", "SE.03", 2.4), ("air_air", "SE.06", 2.0),
    ("exhaust_air", "SE.05", 2.4), ("exhaust_air", "SE.06", 2.75)])
def test_cop_follows_pump_type_and_era(monkeypatch, typed, pump_type, era, cop):
    monkeypatch.setattr("epsm.legacy_records._observed_systems", lambda record: heat_pump(pump_type))
    receipt = Receipt("test")
    heating = _delivery(None, ModelPolicy(), receipt, era=era).heating
    assert set(heating.heat_pump_cop.hourly(2023)) == {cop}
    assert receipt.identities["heat_pump_type"] == pump_type
    assert receipt.identities["heating_delivery_template"] == f"epsm.heating.heat_pump_{pump_type}"


def test_unknown_pump_type_keeps_the_field_average_and_says_so(monkeypatch, typed):
    monkeypatch.setattr("epsm.legacy_records._observed_systems", lambda record: heat_pump(None))
    receipt = Receipt("test")
    heating = _delivery(None, ModelPolicy(), receipt, era="SE.04").heating
    assert set(heating.heat_pump_cop.hourly(2023)) == {2.75}
    assert "heat_pump_type" not in receipt.identities
    assert any("not reported" in note for note in receipt.assumptions)


def test_policy_switch_restores_the_field_average(monkeypatch, typed):
    monkeypatch.setattr("epsm.legacy_records._observed_systems", lambda record: heat_pump("air_air"))
    receipt = Receipt("test")
    heating = _delivery(None, ModelPolicy(heat_pump_cop_by_type=False), receipt, era="SE.04").heating
    assert set(heating.heat_pump_cop.hourly(2023)) == {2.75}
    assert "heat_pump_type" not in receipt.identities


def test_older_data_without_typed_cop_falls_back(monkeypatch):
    monkeypatch.setattr("epsm_data.templates.heating_delivery_template", untyped_template)
    monkeypatch.setattr("epsm.legacy_records._observed_systems", lambda record: heat_pump("air_air"))
    receipt = Receipt("test")
    heating = _delivery(None, ModelPolicy(), receipt, era="SE.04").heating
    assert set(heating.heat_pump_cop.hourly(2023)) == {2.75}
    assert any("no COP by heat-pump type" in note for note in receipt.quality)


def test_policy_version_six():
    assert ModelPolicy().version == "6"
    assert ModelPolicy().heat_pump_cop_by_type is True
