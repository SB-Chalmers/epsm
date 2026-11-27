"""School and office SE.06 earlier-build envelope (before the BBR 19 limits of 2012)."""

import pytest
from shapely.geometry import box

pytest.importorskip("epsm_core")
db = pytest.importorskip("epsm_db")

import epsm.legacy_records as lr  # noqa: E402


def _call(year, kind="school", state="existing", overrides=None, policy=None):
    record = db.BuildingRecord(
        "test", "b", db.BuildingType(kind), box(0, 0, 10, 10), {}
    )
    receipt = db.Receipt("test")
    out = lr._school_earlier_build(
        record, policy or lr.ModelPolicy(), year, state, overrides or {}, receipt
    )
    return out, receipt


@pytest.mark.parametrize("year", [2006, 2009, 2011])
def test_before_2012(year):
    out, receipt = _call(year)
    assert out is True
    assert receipt.identities["school_earlier_build"] == {
        "year": year,
        "before_year": 2012,
        "donor_year": 2005,
    }
    assert any("School SE.06 earlier-build envelope" in a for a in receipt.assumptions)


@pytest.mark.parametrize("year", [2012, 2015, 2021])
def test_from_2012_unchanged(year):
    out, receipt = _call(year)
    assert out is False
    assert "school_earlier_build" not in receipt.identities


@pytest.mark.parametrize("year", [2005, 2022])
def test_other_eras_unchanged(year):
    assert _call(year)[0] is False


@pytest.mark.parametrize("state", ["standard", "advanced"])
def test_only_existing_state(state):
    assert _call(2008, state=state)[0] is False


def test_caller_components_win():
    overrides = {
        "component_states": {"wall": "standard"},
        "component_sources": {"wall": "survey"},
    }
    assert _call(2008, overrides=overrides)[0] is False


def test_disabled_restores_version_12():
    assert (
        _call(2008, policy=lr.ModelPolicy(school_se06_earlier_build=False))[0] is False
    )


def test_policy_version():
    assert lr.ModelPolicy().version == "13"


@pytest.mark.parametrize("year", [2006, 2011])
def test_office_before_2012_uses_office_se05(year):
    out, receipt = _call(year, kind="office")
    assert out is True
    assert receipt.identities["office_earlier_build"]["year"] == year
    assert any("Office SE.06 earlier-build envelope" in a for a in receipt.assumptions)


def test_office_switch_off_restores_earlier_behaviour():
    out, receipt = _call(2008, kind="office", policy=lr.ModelPolicy(office_se06_earlier_build=False))
    assert out is False
    assert "office_earlier_build" not in receipt.identities


@pytest.mark.parametrize("kind", ["multi_family", "single_family"])
def test_housing_unchanged(kind):
    assert _call(2008, kind=kind)[0] is False
