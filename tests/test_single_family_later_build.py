"""Policy version 11: single-family SE.06 later-build envelope (2009/2012 energy rules)."""

from types import SimpleNamespace

import pytest
from shapely.geometry import box

pytest.importorskip("epsm_core")
db = pytest.importorskip("epsm_db")

import epsm.legacy_records as lr  # noqa: E402


def _call(monkeypatch, year, carrier, kind="single_family", state="existing", overrides=None, policy=None):
    monkeypatch.setattr(lr, "_observed_systems", lambda record: SimpleNamespace(heating_carrier=carrier))
    record = db.BuildingRecord("test", "b", db.BuildingType(kind), box(0, 0, 10, 10), {})
    receipt = db.Receipt("test")
    out = lr._single_family_later_build(record, policy or lr.ModelPolicy(), year, state, overrides or {}, receipt)
    return out, receipt


@pytest.mark.parametrize("carrier", ["heat_pump", "electric_direct"])
@pytest.mark.parametrize("year", [2009, 2011, 2015, 2021])
def test_electric_from_2009(monkeypatch, carrier, year):
    out, receipt = _call(monkeypatch, year, carrier)
    states, sources = out
    assert set(states) == set(lr.LATER_BUILD_ROLES)
    assert set(states.values()) == {"advanced"}
    assert set(sources) == set(states) and all("version 11" in s for s in sources.values())
    assert receipt.identities["single_family_later_build"]["carrier"] == carrier
    assert any("not a renovation" in a for a in receipt.assumptions)


@pytest.mark.parametrize("carrier", ["district_heat", "fuel", None])
def test_other_carriers_from_2012(monkeypatch, carrier):
    assert _call(monkeypatch, 2011, carrier)[0] is None
    assert _call(monkeypatch, 2012, carrier)[0] is not None


@pytest.mark.parametrize("year", [2006, 2008])
def test_before_2009_unchanged(monkeypatch, year):
    out, receipt = _call(monkeypatch, year, "heat_pump")
    assert out is None
    assert "single_family_later_build" not in receipt.identities


@pytest.mark.parametrize("year", [2005, 2022])
def test_other_eras_unchanged(monkeypatch, year):
    assert _call(monkeypatch, year, "heat_pump")[0] is None


@pytest.mark.parametrize("state", ["standard", "advanced"])
def test_only_existing_state(monkeypatch, state):
    assert _call(monkeypatch, 2015, "heat_pump", state=state)[0] is None


@pytest.mark.parametrize("kind", ["multi_family", "office", "school"])
def test_only_single_family(monkeypatch, kind):
    assert _call(monkeypatch, 2015, "heat_pump", kind=kind)[0] is None


def test_caller_components_win(monkeypatch):
    overrides = {"component_states": {"wall": "standard"}, "component_sources": {"wall": "survey"}}
    assert _call(monkeypatch, 2015, "heat_pump", overrides=overrides)[0] is None


def test_disabled_restores_version_10(monkeypatch):
    policy = lr.ModelPolicy(single_family_se06_later_build=False)
    assert _call(monkeypatch, 2015, "heat_pump", policy=policy)[0] is None
