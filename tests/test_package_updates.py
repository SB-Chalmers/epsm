# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Current Core inputs, explicit RC choices and the renovation LCA connection."""

# ruff: noqa: F811

from dataclasses import replace
from pathlib import Path

import pytest
from test_platform import (  # noqa: F401
    assessment,
    engine,
    reference,
    replacement,
    weather,
)

from epsm import Building
from epsm.results import Evaluation, identity


def test_engine_executable_paths_have_a_portable_identity():
    assert identity({"energyplus": Path("/example/energyplus")}) == identity(
        {"energyplus": "/example/energyplus"}
    )


def test_saved_evaluation_cannot_relabel_energy_for_a_different_state(
    tmp_path, weather, engine
):
    result = reference().simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
    data = result.to_dict()
    data["state_id"] = "a-different-building-state"
    with pytest.raises(ValueError, match="state"):
        Evaluation.from_dict(data).annual_energy()


def test_building_defaults_and_new_physical_inputs_follow_core():
    assert Building().geometry is None
    building = reference()
    building.thermal_bridge_uplift_fraction = 0.12
    building.load_reference_area_m2 = 600
    building.operation = building.operation.updated(equipment_gain_w_m2=8)
    restored = Building.from_dict(building.to_dict())
    assert restored.snapshot().sha256 == building.snapshot().sha256
    assert restored.foundation == building.foundation
    assert restored.thermal_bridge_uplift_fraction == 0.12
    assert restored.effective_load_reference_area_m2 == 600
    assert restored.operation.gain_partitions == building.operation.gain_partitions


def test_evaluation_supplies_energy_to_the_complete_renovation_path(
    tmp_path, weather, engine
):
    from epsm_lca import AnnualEnergy as LCAEnergy

    from epsm import AnnualEnergy, RenovationResult, assess_renovation

    assert AnnualEnergy is LCAEnergy
    baseline = reference()
    baseline.assessment = assessment(baseline)
    original = baseline.snapshot().sha256
    one = baseline.renovate(replacement(baseline))
    two = one.renovate(replacement(one, "second-window"))
    evaluations = [
        state.simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
        for state in (baseline, one, two)
    ]
    supplied = {step: result.annual_energy() for step, result in enumerate(evaluations)}
    report = assess_renovation(two, baseline.assessment, energy=supplied)
    assert isinstance(report, RenovationResult) and report.complete
    for row, evaluation in zip(report.table(), evaluations):
        assert row["total_kgco2e"] == pytest.approx(evaluation.lca.total_gwp_kgco2e)
        assert evaluation.id in supplied[row["step"]].source
        assert evaluation.energy_id in supplied[row["step"]].source
    assert report.stages[1].material_so_far_kgco2e == pytest.approx(
        2 * report.stages[0].material_kgco2e
    )
    assert report.stages[0].removed_quantities
    assert baseline.snapshot().sha256 == original
    baseline.operation = baseline.operation.updated(equipment_gain_w_m2=9)
    assert evaluations[0].annual_energy().state_id == original
    path = report.save(tmp_path / "renovation.json")
    assert RenovationResult.load(path) == report
    with pytest.raises(ValueError, match="state"):
        assess_renovation(
            two, baseline.assessment, energy={0: evaluations[1].annual_energy()}
        )


@pytest.mark.parametrize(
    "changed, message",
    [
        ({"annual": False}, "annual"),
        ({"requirements": ["missing heating delivery"]}, "complete"),
        ({"diagnostics": {"accepted": False}}, "complete"),
    ],
)
def test_incomplete_energy_cannot_be_presented_as_supplied_annual_energy(
    tmp_path, weather, engine, changed, message
):
    result = reference().simulate(engine="epsm_rc", weather=weather, directory=tmp_path)
    data = result.to_dict()
    data["energy"].update(changed)
    with pytest.raises(ValueError, match=message):
        Evaluation.from_dict(data).annual_energy()


def test_engine_choices_and_core_physical_changes_invalidate_energy_cache(
    tmp_path, weather, engine
):
    from epsm_rc import RCSettings

    building = reference()
    settings = RCSettings.from_policy(
        "epsm_rc_5r1c_v1",
        airflow_policy="sensible_only_unlimited_supply",
        ground_policy="conductance_multiplier",
    )

    def run(config):
        return building.simulate(
            engine="epsm_rc", weather=weather, settings=config, directory=tmp_path
        )

    first = run(settings)
    assert run(settings).energy_id == first.energy_id
    changed = run(replace(settings, ground_coupling_factor=0.7))
    assert changed.energy_id != first.energy_id
    building.thermal_bridge_uplift_fraction = 0.15
    bridge = run(settings)
    assert bridge.energy_id not in {first.energy_id, changed.energy_id}
    building.load_reference_area_m2 = 600
    area = run(settings)
    assert area.energy_id != bridge.energy_id
    assert len(engine) == 4
