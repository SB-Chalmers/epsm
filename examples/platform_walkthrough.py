# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Run actual annual energy and renovation LCA with installed EPSM packages.

Data supplies catalogue constructions and Boverket material factors. Building,
delivery, removal and carrier climate factors are teaching assumptions. Supply
an EPW with --weather, or use RC's bundled Gothenburg example. Each call saves
its results in a new folder below --output.
"""

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from importlib.resources import files
from math import isclose
from pathlib import Path
from uuid import uuid4

from renovation_case import make_case, rc_settings

from epsm import EvaluationCache, Weather, assess_renovation


def run_case(
    *, output, weather=None, engine="epsm_rc", energyplus=None, optimise=False
):
    """Evaluate baseline, bundled work and two stages, then save both reports."""
    if engine not in {"epsm_rc", "energyplus"}:
        raise ValueError("Choose epsm_rc or energyplus")
    case = make_case()
    baseline_id = case["baseline"].snapshot().sha256
    weather = (
        weather
        if isinstance(weather, Weather)
        else Weather.from_epw(weather or files("epsm_rc") / "data/epw/goteborg.epw")
    )
    options = {"settings": rc_settings()} if engine == "epsm_rc" else {}
    if energyplus is not None:
        if engine != "energyplus":
            raise ValueError(
                "energyplus executable is only used by the energyplus engine"
            )
        options["energyplus"] = energyplus
    directory = Path(output) / (
        datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    )
    cache = EvaluationCache(directory / "cache")
    evaluations = {
        name: case[name].simulate(
            engine=engine,
            weather=weather,
            cache=cache,
            directory=directory / name,
            **options,
        )
        for name in ("baseline", "single_step", "step_1", "step_2")
    }
    energy = {name: result.annual_energy() for name, result in evaluations.items()}
    staged = assess_renovation(
        case["step_2"],
        case["settings"],
        energy={0: energy["baseline"], 1: energy["step_1"], 2: energy["step_2"]},
    )
    single = assess_renovation(
        case["single_step"],
        case["settings"],
        energy={0: energy["baseline"], 1: energy["single_step"]},
    )
    assert single.complete and staged.complete, (single.summary(), staged.summary())
    assert isclose(
        single.stages[-1].total_kgco2e, staged.stages[-1].total_kgco2e, rel_tol=1e-10
    )
    assert case["baseline"].snapshot().sha256 == baseline_id
    for name, report in (("single-step", single), ("staged", staged)):
        report.save(directory / f"{name}-report.json")
        with (directory / f"{name}-table.csv").open(
            "x", newline="", encoding="utf-8"
        ) as stream:
            rows = report.table()
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary = {
        name: {
            "annual_delivered_kwh": result.energy.annual_delivered_energy_kwh,
            "delivered_by_carrier": result.energy.delivered_by_carrier,
            "evaluation_id": result.id,
            "energy_id": result.energy_id,
            "energy_reused": result.diagnostics["energy_reused"],
            "engine_diagnostics": result.energy.diagnostics,
        }
        for name, result in evaluations.items()
    }
    with (directory / "energy-summary.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
    if optimise:
        from epsm_data import RenovationCatalogue
        from epsm_workflows import optimise_renovations

        tree = optimise_renovations(
            case["baseline"],
            catalogue=RenovationCatalogue(list(case["measures"])),
            max_depth=1,
            budget=3,
            evaluator=lambda candidate: candidate.simulate(
                engine=engine,
                weather=weather,
                cache=cache,
                directory=directory / "search",
                **options,
            ),
        )
        assert all(node.feasible for node in tree.nodes), [
            node.reasons for node in tree.nodes if not node.feasible
        ]
        with (directory / "search-tree.json").open("x", encoding="utf-8") as stream:
            json.dump(tree.to_dict(), stream, indent=2, allow_nan=False)
        print(
            f"Evaluated {len(tree.nodes)} alternatives; Pareto alternatives: {len(tree.pareto)}"
        )
    return dict(
        case=case,
        evaluations=evaluations,
        staged=staged,
        single=single,
        directory=directory,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weather", type=Path)
    parser.add_argument(
        "--output", type=Path, default=Path("outputs/platform_walkthrough")
    )
    parser.add_argument(
        "--engine", choices=("epsm_rc", "energyplus"), default="epsm_rc"
    )
    parser.add_argument("--energyplus-exe", type=Path)
    parser.add_argument(
        "--optimise",
        action="store_true",
        help="Also run Workflows; requires epsm[workflows]",
    )
    parser.add_argument(
        "--log-level", choices=("WARNING", "INFO", "DEBUG"), default="WARNING"
    )
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level)
    result = run_case(
        output=args.output,
        weather=args.weather,
        engine=args.engine,
        energyplus=args.energyplus_exe,
        optimise=args.optimise,
    )
    for row in result["staged"].table():
        print(row)
    print(
        "Removed materials:",
        result["staged"].quantities(action="removed", by_material=True),
    )
    print("Saved results:", result["directory"].resolve())


if __name__ == "__main__":
    main()
