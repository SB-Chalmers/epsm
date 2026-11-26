"""Single-family slab edge beam and BEN småhus household electricity."""

import pytest
from shapely.geometry import box

pytest.importorskip("epsm_core")
db = pytest.importorskip("epsm_db")

from epsm_core import Footprint, GeometrySpec  # noqa: E402
from epsm_core.specs.physics import ConstructionSpec, LayerSpec, MaterialSpec  # noqa: E402

from epsm.legacy_records import ModelPolicy, _foundation, _operation  # noqa: E402


def _material(k, rho=30.0, cp=1400.0):
    return MaterialSpec(
        name=f"m{k}", conductivity_w_mk=k, density_kg_m3=rho, specific_heat_j_kgk=cp
    )


class _Envelope:
    def __init__(self, ground):
        self.ground = ground


def _ground(insulation_m=0.25):
    return ConstructionSpec(
        layers=(
            LayerSpec(material=_material(0.037), thickness_m=insulation_m),
            LayerSpec(material=_material(2.3, 2300.0, 900.0), thickness_m=0.12),
        )
    )


def _record(kind="single_family"):
    return db.BuildingRecord(
        "test", "house", db.BuildingType(kind), box(0, 0, 10, 10), {}
    )


def _geometry(basement=0.0):
    geometry = GeometrySpec.from_footprint(
        Footprint.rectangle(10, 10), storeys=1, storey_height_m=3
    )
    return geometry.updated(basement_depth_m=basement) if basement else geometry


def test_insulated_single_family_slab_gets_an_edge_beam():
    receipt = db.Receipt("test")
    f = _foundation(
        _record(), _Envelope(_ground()), _geometry(), ModelPolicy(), receipt
    )
    assert f.wall_depth_below_slab_m == 0.3
    layers = f.footing_wall.layers
    assert layers[0].thickness_m == pytest.approx(0.10)
    assert layers[0].material.conductivity_w_mk == pytest.approx(0.037)
    assert layers[1].material.conductivity_w_mk == pytest.approx(2.3)
    assert any("kantelement" in a for a in receipt.assumptions)


def test_edge_beam_never_thicker_than_the_slab_insulation():
    f = _foundation(
        _record(), _Envelope(_ground(0.07)), _geometry(), ModelPolicy(), db.Receipt("t")
    )
    assert f.footing_wall.layers[0].thickness_m == pytest.approx(0.07)


@pytest.mark.parametrize(
    "case", ["multi_family", "uninsulated", "basement", "disabled"]
)
def test_edge_beam_only_for_insulated_single_family_slabs(case):
    record = _record("multi_family" if case == "multi_family" else "single_family")
    ground = _ground(0.03) if case == "uninsulated" else _ground()
    geometry = _geometry(2.5) if case == "basement" else _geometry()
    policy = (
        ModelPolicy(single_family_slab_edge_insulation_m=0)
        if case == "disabled"
        else ModelPolicy()
    )
    f = _foundation(record, _Envelope(ground), geometry, policy, db.Receipt("t"))
    assert f.footing_wall is None and f.wall_depth_below_slab_m == 0


def _annual_gain(use):
    s = use.equipment_fraction
    hours = (
        sum(s.annual_values)
        if s.annual_values is not None
        else sum(s.values) / len(s.values) * 8760
    )
    return use.equipment_gain_w_m2 * hours / 1000


@pytest.mark.parametrize("year", [2023, 2024])
def test_single_family_household_heat_follows_ben_smahus(year):
    options = dict(
        ventilation="F",
        infiltration={"envelope_infiltration_ach": 0.05},
        geometry=_geometry(),
        area=90,
    )
    v6, _, _ = _operation(
        "residential",
        year,
        policy=ModelPolicy(single_family_household_electricity_kwh_m2=None),
        receipt=db.Receipt("t"),
        **options,
    )
    receipt = db.Receipt("t")
    v7, _, _ = _operation(
        "residential", year, policy=ModelPolicy(), receipt=receipt, **options
    )
    assert _annual_gain(v6) == pytest.approx(
        14.7, rel=0.02
    )  # Sveby multi-family 21 x 0.70
    assert _annual_gain(v7) == pytest.approx(21.0, rel=1e-9)  # BEN småhus 30 x 0.70
    assert v7.equipment_fraction == v6.equipment_fraction  # monthly shape kept
    assert any("BEN BFS 2016:12" in a for a in receipt.assumptions)
    mf, _, _ = _operation(
        "residential",
        year,
        policy=ModelPolicy(),
        receipt=db.Receipt("t"),
        residential_type="multi_family",
        **options,
    )
    assert _annual_gain(mf) == pytest.approx(_annual_gain(v6))


def test_v7_policy_bounds():
    with pytest.raises(ValueError):
        ModelPolicy(single_family_slab_edge_insulation_m=-0.1)
    with pytest.raises(ValueError):
        ModelPolicy(household_electricity_heat_fraction=1.5)
