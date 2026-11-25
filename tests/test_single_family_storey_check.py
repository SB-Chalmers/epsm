"""Single-family storey check against EPC Atemp or register living area (policy version 6)."""

from datetime import date

import pytest
from shapely.geometry import box

pytest.importorskip("epsm_core")
db = pytest.importorskip("epsm_db")

from epsm.legacy_records import ModelPolicy, _geometry  # noqa: E402


def _record(
    *,
    height,
    roof="unclear",
    eave=None,
    ridge=None,
    kind="single_family",
    atemp=None,
    living="150",
    storeys=None,
    size=12.0,
):
    footprint = box(0, 0, size, size)
    facts = {
        "geometry_valid": True,
        "object_status": "Gällande",
        "construction_year": 2023,
        "attributes": {
            "original_values": {"Byggnad/Bostad/totalBoarea": [living]}
            if living
            else {}
        },
    }
    certificates = observations = subjects = ()
    if atemp is not None or storeys is not None:
        certificates = (
            {
                "certificate_id": "epc",
                "certificate_date": date(2024, 5, 1),
                "subject_count": 1,
                "loaded_building_count": 1,
                "date_status": "verified",
                "matching_status": "fully_matched",
            },
        )
        subjects = ({"certificate_id": "epc"},)
        observations = tuple(
            {
                "certificate_id": "epc",
                "source_field": name,
                "raw_values": [str(value)],
                "normalized_value": {"value": value},
                "value_status": "available",
            }
            for name, value in (("EgenAtemp", atemp), ("EgenAntalPlan", storeys))
            if value is not None
        )
    return db.BuildingRecord(
        "test",
        "house",
        db.BuildingType(kind),
        footprint,
        facts,
        components=({"component_id": 1, "geometry": footprint},),
        heights=(
            {
                "component_id": 1,
                "height_status": "determined",
                "roof_form": roof,
                "representative_height_m": height,
                "eave_height_m": eave,
                "ridge_height_m": ridge,
                "attributes": {"geometry_status": "consistent_source_component"},
            },
        ),
        certificates=certificates,
        subjects=subjects,
        observations=observations,
        epc_results=({"certificate_id": "epc", "status": "matched"},)
        if certificates
        else (),
    )


def _floors(record, policy=None):
    receipt = db.Receipt("test", "house")
    geometry = _geometry(record, policy or ModelPolicy(), receipt, {})
    return [part.floors for part in geometry.parts], geometry, receipt


def test_tree_canopy_height_becomes_area_implied_bungalow():
    # 144 m2 footprint, 150 m2 living area, 15 m "height" from trees: version 5 gives 5 storeys.
    record = _record(height=15.2, roof="pitched_ridge", eave=14.9, ridge=16.6)
    assert _floors(record, ModelPolicy(single_family_storey_check=False))[0] == [5]
    floors, geometry, receipt = _floors(record)
    assert floors == [1]
    part = geometry.parts[0]
    assert part.storey_elevations_m[-1] == pytest.approx(3.0)
    assert part.roof.shape == "flat"
    assert any("register living area" in a for a in receipt.assumptions)


def test_epc_atemp_is_preferred_over_register_area():
    record = _record(height=8.9, atemp=250.0, living="120")
    floors, _, receipt = _floors(record)
    assert floors == [2]
    assert any("EPC Atemp" in a for a in receipt.assumptions)


def test_plausible_heights_are_unchanged():
    assert _floors(_record(height=3.4))[0] == [1]
    assert _floors(_record(height=5.8, living="240"))[0] == [2]


def test_valid_reported_epc_storeys_are_kept():
    # EPC storeys fit the floor-height bounds, so the check does not run.
    floors, _, receipt = _floors(_record(height=5.8, atemp=120.0, storeys=2))
    assert floors == [2]
    assert not any("implausible for a single-family" in a for a in receipt.assumptions)


def test_two_storeys_on_single_storey_area_drop_to_one():
    assert _floors(_record(height=5.8, living="120"))[0] == [1]


def test_without_area_evidence_height_inference_stands():
    assert _floors(_record(height=15.2, living=None))[0] == [5]


def test_other_types_are_not_checked():
    assert _floors(_record(height=15.2, kind="multi_family"))[0] == [5]


def test_policy_bounds_are_validated():
    with pytest.raises(ValueError):
        ModelPolicy(single_family_minimum_area_ratio=1.5)
    with pytest.raises(ValueError):
        ModelPolicy(single_family_maximum_storeys=0)
    assert ModelPolicy().version == "12"
