"""Shading-only neighbour context on the record route, synthetic inputs only."""

from importlib.resources import files

import pytest
from shapely.geometry import box
from test_archetype_consumers import (
    _legacy_record,  # synthetic 10 m x 10 m record at (0, 0)-(10, 10)
)

from epsm._context import context_spec
from epsm.legacy_records import EPSMBuilding, ModelPolicy


@pytest.fixture
def weather():
    from epsm_db.weather import WeatherReference

    return WeatherReference.from_epw(
        files("epsm_rc") / "data/epw/goteborg.epw", calendar_year=2023
    )


def rows():
    return [
        {
            "id": "touching-target",
            "height_m": 9.0,
            "geometry": box(5, 5, 15, 15),
        },  # overlaps the target
        {
            "id": "garden-shed",
            "height_m": 1.5,
            "geometry": box(30, 0, 33, 3).wkt,
        },  # below 2 m
        {"id": "tall-block", "height_m": 18.0, "geometry": box(20, 0, 30, 10)},
        {
            "id": "lower-annex",
            "height_m": 6.0,
            "geometry": box(25, 0, 35, 10),
        },  # half under tall-block
        {
            "id": "jagged",
            "height_m": 7.0,
            "geometry": "POLYGON((0 20, 10 20, 10.001 20.0005, 10 30, 0 30, 0 20))",
        },  # near-coincident vertex
    ]


def test_rules_drop_overlap_low_and_trim_lower_neighbours():
    from epsm_core.specs.geometry import Footprint

    target = [Footprint(exterior=((-5, -5), (5, -5), (5, 5), (-5, 5)))]
    context, dropped = context_spec(
        rows(),
        origin_xy=(5, 5),
        target_footprints=target,
        min_height_m=2.0,
        radius_m=100,
    )
    ids = [b.identifier for b in context.buildings]
    assert ids == ["tall-block", "jagged", "lower-annex"]  # tallest first
    assert dropped == {"overlap": 1, "low": 1, "covered": 0}
    annex = next(b for b in context.buildings if b.identifier == "lower-annex")
    xs = [x for x, _ in annex.footprints[0].exterior]
    assert (
        min(xs) >= 25 - 5 + 0.1 - 1e-6
    )  # trimmed clear of the taller block (model frame, origin (5, 5))
    jagged = next(b for b in context.buildings if b.identifier == "jagged")
    assert len(jagged.footprints[0].exterior) == 4


def test_record_route_attaches_caller_rows(weather):
    building, receipt = EPSMBuilding.from_record(
        _legacy_record(),
        weather=weather,
        preflight=False,
        overrides={"context_rows": rows()},
    )
    assert len(building.spec.context.buildings) == 3
    assert receipt.fields["context_buildings"]["model_value"] == 3
    assert "context_rows" not in receipt.identities["overrides"]


def test_context_can_be_turned_off(weather):
    building, _ = EPSMBuilding.from_record(
        _legacy_record(),
        weather=weather,
        preflight=False,
        policy=ModelPolicy(context_radius_m=None),
        overrides={"context_rows": rows()},
    )
    assert building.spec.context.buildings == ()


def test_portable_record_without_rows_has_no_context_and_says_so(weather):
    building, receipt = EPSMBuilding.from_record(
        _legacy_record(), weather=weather, preflight=False
    )
    assert building.spec.context.buildings == ()
    assert any("no shading context" in note for note in receipt.quality)


def test_overlap_is_checked_against_the_prepared_model_footprint():
    """A neighbour that misses the source outline but overlaps the prepared footprint is dropped."""
    from epsm_core.specs.geometry import Footprint

    prepared = [
        Footprint(exterior=((-5, -5), (6, -5), (6, 5), (-5, 5)))
    ]  # 1 m wider than the source
    near = [{"id": "close", "height_m": 8.0, "geometry": box(10.5, 0, 14, 10)}]
    context, dropped = context_spec(
        near,
        origin_xy=(5, 5),
        target_footprints=prepared,
        min_height_m=2.0,
        radius_m=100,
    )
    assert context.buildings == () and dropped["overlap"] == 1


@pytest.mark.parametrize("radius", [0, -1, float("inf"), True])
def test_policy_rejects_bad_radius(radius):
    with pytest.raises(ValueError):
        ModelPolicy(context_radius_m=radius)


def test_policy_version_six_has_context_on_by_default():
    assert ModelPolicy().version == "13" and ModelPolicy().context_radius_m == 100.0


def test_cleaned_neighbour_never_overlaps_target():
    """A lake neighbour (relative coordinates) whose cleaned outline crept 0.002 m2 over a school."""
    from shapely.geometry import Polygon

    from epsm._context import context_spec
    from epsm_core.specs.geometry import Footprint

    target = Footprint(exterior=((-28.031, -0.996), (21.234, -20.487), (29.363, 0.271), (-22.72, 20.831)))
    rows = [{"id": "n1", "height_m": 12.14, "geometry": 'MULTIPOLYGON (((-61.260 10.234, -43.518 67.449, -18.151 62.229, -18.220 61.957, -12.661 60.550, -17.269 42.345, -22.720 20.831, -28.031 -0.996, -61.260 10.234)))'}]
    spec, _ = context_spec(rows, origin_xy=(0.0, 0.0), target_footprints=[target], min_height_m=2.0, radius_m=100.0)
    assert spec.buildings
    tp = Polygon(target.exterior)
    for building in spec.buildings:
        for fp in building.footprints:
            assert Polygon(fp.exterior).intersection(tp).area <= 1e-9


def test_clipped_neighbour_has_no_short_edges():
    """After the extra clip, no two consecutive context vertices are closer than MIN_EDGE_M."""
    import math

    from shapely.geometry import Polygon

    from epsm._context import MIN_EDGE_M, _clip

    target = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    # The clearance cut leaves a 4 mm step next to the target corner.
    neighbour = Polygon([(10.05, -1.0), (15.0, -1.0), (15.0, 11.0), (10.104, 11.0), (10.104, 10.104), (10.1, 10.1), (10.05, 5.0)])
    clipped = _clip(neighbour, target)
    assert clipped is not None
    pts = list(clipped.exterior.coords)
    assert all(math.dist(a, b) >= MIN_EDGE_M for a, b in zip(pts, pts[1:]))
    assert clipped.intersection(target).area <= 1e-9
