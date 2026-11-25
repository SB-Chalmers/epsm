"""Policy version 10: EPC ventilation with FTX among several ticked systems is modelled as FTX."""

import pytest
from shapely.geometry import box

pytest.importorskip("epsm_core")
db = pytest.importorskip("epsm_db")

from epsm_db.epc_systems import observed_systems_from_raw  # noqa: E402

import epsm.legacy_records as lr  # noqa: E402

FIELDS = {"S": "VentTypSjalvdrag", "F": "VentTypF", "Fmed": "VentTypFmed", "FT": "VentTypFT", "FTX": "VentTypFTX"}


def _observed(*ticked):
    raw = {field: ["Ja" if kind in ticked else "Nej"] for kind, field in FIELDS.items()}
    return observed_systems_from_raw("efter_v260:1", raw)


def _ventilation(monkeypatch, kind, *ticked, policy=None):
    monkeypatch.setattr(lr, "_observed_systems", lambda record: _observed(*ticked))
    record = db.BuildingRecord("test", "b", db.BuildingType(kind), box(0, 0, 10, 10), {})
    receipt = db.Receipt("test")
    return lr._ventilation(record, policy or lr.ModelPolicy(), receipt, None), receipt


@pytest.mark.parametrize("kind", ["office", "school", "multi_family"])
@pytest.mark.parametrize("ticked", [("F", "FTX"), ("FT", "FTX"), ("F", "FT", "FTX"), ("S", "FTX")])
def test_ftx_among_several_systems_is_modelled_as_ftx(monkeypatch, kind, ticked):
    result, receipt = _ventilation(monkeypatch, kind, *ticked)
    assert result == "FTX"
    # Reported, so the catalogue's observed-FTX template is used rather than the era default.
    assert receipt.fields["ventilation"]["model_state"] == "reported_raw_mapping"
    assert any("version 10" in a for a in receipt.assumptions)


def test_conflict_without_ftx_keeps_the_type_default(monkeypatch):
    result, receipt = _ventilation(monkeypatch, "office", "F", "FT")
    assert result == "FTX"  # office type default
    assert receipt.fields["ventilation"]["model_state"] == "assumed"
    assert any("era's default template" in a for a in receipt.assumptions)


def test_single_system_is_unchanged(monkeypatch):
    result, receipt = _ventilation(monkeypatch, "office", "FT")
    assert result == "FT"
    assert not any("version 10" in a for a in receipt.assumptions)


def test_disabled_restores_version_9(monkeypatch):
    result, receipt = _ventilation(monkeypatch, "office", "F", "FTX",
                                   policy=lr.ModelPolicy(ventilation_conflict_ftx=False))
    assert receipt.fields["ventilation"]["model_state"] == "assumed"
