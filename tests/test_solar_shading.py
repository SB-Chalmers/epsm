"""Sveby window solar shading is on by default in the record and archetype routes."""

from dataclasses import replace

import pytest
from epsm_data import Archetype, OperatingProfile
from test_archetype_consumers import _legacy_record
from test_platform import engine, reference, replacement, weather  # noqa: F401

from epsm._solar_shading import (
    solar_shading_factor,
    sveby_shading_factors,
    validate_solar_shading,
)


def _profile_values(use):
    from epsm_data import select_operating_profile

    return select_operating_profile(use).values


@pytest.mark.parametrize(
    "use, behaviour, total",
    [
        ("single_family", 0.71, 0.5),
        ("multi_family", 0.71, 0.5),
        ("office", 0.71, 0.5),
        ("school", 0.65, 0.65),
    ],
)
def test_sveby_factors_come_from_the_data_profiles(use, behaviour, total):
    values = _profile_values(use)
    assert sveby_shading_factors(values) == {"behaviour": behaviour, "total": total}
    assert solar_shading_factor(values, "behaviour")[0] == behaviour
    assert solar_shading_factor(values, "total")[0] == total
    assert solar_shading_factor(values, None)[0] == 1.0
    assert solar_shading_factor(values, 0.8)[0] == 0.8


def test_profile_without_sveby_shading_resolves_to_nothing():
    assert solar_shading_factor({}, "behaviour") == (None, None)
    assert solar_shading_factor({}, None)[0] == 1.0


@pytest.mark.parametrize("choice", ["sveby", "", 0, 1.5, float("nan"), True, "0.7"])
def test_invalid_choices_are_rejected(choice):
    with pytest.raises(ValueError):
        validate_solar_shading(choice)


def test_policy_defaults_to_behaviour_and_validates():
    from epsm.legacy_records import ModelPolicy

    policy = ModelPolicy()
    assert policy.solar_shading == "behaviour"
    assert policy.version == "12"
    assert ModelPolicy(solar_shading=None).solar_shading is None
    with pytest.raises(ValueError):
        ModelPolicy(solar_shading="all")


def _record_route(policy=None, record=None):
    pytest.importorskip("epsm_db")
    from importlib.resources import files

    from epsm_db.weather import WeatherReference

    from epsm.legacy_records import EPSMBuilding

    climate = WeatherReference.from_epw(
        files("epsm_rc") / "data/epw/goteborg.epw", calendar_year=2023
    )
    kwargs = {} if policy is None else {"policy": policy}
    return EPSMBuilding.from_record(
        record or _legacy_record(), weather=climate, preflight=False, **kwargs
    )


@pytest.mark.parametrize(
    "choice, expected", [("behaviour", 1.0), ("total", 1.0), (None, 1.0), (0.9, 0.9)]
)
def test_record_route_sets_the_facade_factor(choice, expected):
    from epsm.legacy_records import ModelPolicy

    built, receipt = _record_route(ModelPolicy(solar_shading=choice))
    assert built.spec.facade.solar_shading_factor == expected
    assert receipt.fields["solar_shading_factor"]["model_value"] == expected


def test_record_route_default_is_sveby_behaviour_even_with_version_3_facade():
    from epsm_db.enums import BuildingType

    from epsm.legacy_records import ModelPolicy

    sf = replace(_legacy_record(), type=BuildingType.RESIDENTIAL_SINGLE_FAMILY)
    earlier, _ = _record_route(ModelPolicy(version="3", catalogue_templates=False), sf)
    assert earlier.spec.facade.solar_shading_factor == 0.71
    off, _ = _record_route(
        ModelPolicy(version="3", catalogue_templates=False, solar_shading=None), sf
    )
    assert off.spec.facade.solar_shading_factor == 1.0


def test_record_route_school_uses_the_school_factor():
    from epsm_db.enums import BuildingType

    from epsm.legacy_records import ModelPolicy

    record = _legacy_record()
    school = replace(record, type=BuildingType.SCHOOL)
    for choice in ("behaviour", "total"):
        built, _ = _record_route(ModelPolicy(solar_shading=choice), school)
        assert built.spec.facade.solar_shading_factor == 0.65


@pytest.mark.parametrize(
    "archetype_id, choice, expected",
    [
        ("sf_se03", "behaviour", 0.71),
        ("sf_se03", "total", 0.5),
        ("sf_se03", None, 1.0),
        ("mf_se02", "behaviour", 1.0),
        ("mf_se02", "total", 1.0),
        ("mf_se02", None, 1.0),
        ("office_se04", "behaviour", 0.71),
        ("office_se04", "total", 0.5),
        ("school_se04", "behaviour", 0.65),
        ("school_se04", "total", 0.65),
    ],
)
def test_apply_archetype_uses_the_chosen_sveby_factor(archetype_id, choice, expected):
    from epsm_data import Catalogue

    selected = Catalogue.load().get(archetype_id, state="existing")
    b = reference()
    report = b.apply_archetype(selected, solar_shading=choice)
    assert b.facade.solar_shading_factor == expected
    if choice is not None:
        assert any("Sveby" in text and "shading" in text for text in report.assumptions)


def test_apply_archetype_default_matches_the_record_route():
    from epsm_data import Catalogue

    b = reference()
    b.apply_archetype(Catalogue.load().get("sf_se03", state="existing"))
    assert b.facade.solar_shading_factor == 0.71


def test_apply_archetype_rejects_an_unknown_choice_before_changes():
    from epsm_data import Catalogue

    b = reference()
    before = b.snapshot().sha256
    with pytest.raises(ValueError):
        b.apply_archetype(
            Catalogue.load().get("sf_se03", state="existing"), solar_shading="sveby"
        )
    assert b.snapshot().sha256 == before and b.archetype_applications == ()


def test_authored_facade_values_are_kept():
    profile = OperatingProfile(
        "study:facade",
        {"building_assumptions": {"facade": {"solar_shading_factor": 0.4}}},
        ("study:facade",),
    )
    b = reference()
    b.apply_archetype(
        Archetype(
            "research.custom",
            "Authored",
            source_references=("study:x",),
            operating_profile=profile,
        )
    )
    assert b.facade.solar_shading_factor == 0.4


def test_off_choice_does_not_touch_a_profile_without_sveby_shading():
    b = reference()
    before = b.facade.solar_shading_factor
    profile = OperatingProfile(
        "study:use",
        {"building_assumptions": {"use": b.operation.model_dump(mode="json")}},
        ("study:programme",),
    )
    b.apply_archetype(
        Archetype(
            "research.custom",
            "Authored",
            source_references=("study:x",),
            operating_profile=profile,
        ),
        solar_shading=None,
    )
    assert b.facade.solar_shading_factor == before


def test_multi_family_named_choices_are_not_applied_but_numbers_are():
    values = _profile_values("multi_family")
    for choice in ("behaviour", "total"):
        factor, text = solar_shading_factor(values, choice, "multi_family")
        assert factor == 1.0 and "not applied for multi-family" in text
    assert solar_shading_factor(values, 0.8, "multi_family")[0] == 0.8
    assert solar_shading_factor(values, "behaviour", "single_family")[0] == 0.71


def test_record_route_explicit_number_still_applies_to_multi_family():
    from epsm.legacy_records import ModelPolicy

    built, _ = _record_route(ModelPolicy(solar_shading=0.8))
    assert built.spec.facade.solar_shading_factor == 0.8


def test_record_route_single_family_uses_the_behaviour_factor():
    from epsm_db.enums import BuildingType

    sf = replace(_legacy_record(), type=BuildingType.RESIDENTIAL_SINGLE_FAMILY)
    built, _ = _record_route(record=sf)
    assert built.spec.facade.solar_shading_factor == 0.71
