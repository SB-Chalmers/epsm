# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Require installed grid/Jansen execution through actual RC and EnergyPlus.

The teaching inputs verify package connections, row identities and retry behavior.
One labelled transient exception is injected before an evaluator call; successful
results always come from the actual engine. This is not a sensitivity accuracy or
building validation study. Required prerequisites fail rather than skip.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

from check_archetype_handoff import (
    REQUIRED_PACKAGES as _BASE_PACKAGES,
)
from check_archetype_handoff import (
    installed_packages,
    read_receipt,
    require_energyplus,
    sha256,
)

REQUIRED_PACKAGES = (*_BASE_PACKAGES, "epsm_workflows")
PARAMETER = "thermal_bridge_uplift_fraction"
BOUNDARY = "space_heating_and_fans"
EXTRA_OUTPUT = "ZONE AIR RELATIVE HUMIDITY"


def read_workflow_receipt(path):
    """Require exact source evidence for Workflows and its scientific collaborators."""
    receipt = read_receipt(path)
    missing = set(REQUIRED_PACKAGES) - set(receipt["packages"])
    if missing:
        raise RuntimeError(f"Required workflow receipt is missing: {sorted(missing)}")
    return receipt


def metrics_from_rows(rows, identities, states):
    """Read one accepted annual heating/fan metric per row, preserving its identity."""
    from epsm import Evaluation

    if len(rows) != len(identities) or len(states) != len(identities):
        raise ValueError("Expected one successful result per prepared row")
    values = []
    for index, (row, identity, state) in enumerate(zip(rows, identities, states)):
        if row is None or row["status"] != "succeeded":
            raise ValueError("Expected one successful result per prepared row")
        if row["index"] != index or row["case_id"] != identity:
            raise ValueError("Prepared row alignment changed")
        evaluation = Evaluation.from_dict(row["result"])
        if evaluation.state_id != state:
            raise ValueError("Result belongs to a different physical state")
        annual = evaluation.annual_energy()
        if annual.boundary != BOUNDARY:
            raise ValueError("Result energy boundary differs from heating and fans")
        value = sum(annual.delivered_by_carrier.values())
        if not math.isfinite(value) or value < 0:
            raise ValueError("Result energy must be finite and nonnegative")
        values.append(value)
    return values


def _attempt_count(directory):
    return len(list((directory / "attempts").glob("*/*.json")))


def _apply_parameter(building, values):
    building.thermal_bridge_uplift_fraction = values[PARAMETER]


def _run_plan(
    directory, baseline, samples, *, engine, weather, settings, energyplus, design=None
):
    from epsm_workflows import (
        analyse_sensitivity,
        integration,
        parametric_cases,
        prepare,
        read_results,
        run_local,
    )

    from epsm import Building, Evaluation

    options = {"settings": settings}
    if engine == "energyplus":
        options["energyplus"] = energyplus
    cases = parametric_cases(
        baseline,
        samples,
        _apply_parameter,
        engine=engine,
        weather=weather,
        assessment=baseline.assessment,
        simulation_options=options,
    )
    states = [
        Building.from_dict(case.payload["building"]).snapshot().sha256 for case in cases
    ]
    manifest = prepare(
        directory,
        cases,
        environment={
            "acceptance": "installed-workflow-handoff",
            "metric_boundary": BOUNDARY,
            "controlled_fault_injection": design is not None,
        },
    )
    identities = manifest["case_ids"]
    before_retry = None
    if design is not None:
        actual_evaluate = integration.evaluate
        injected = False

        def one_fault(payload):
            nonlocal injected
            if not injected and payload["_execution"]["case_id"] == identities[0]:
                injected = True
                raise RuntimeError(
                    "CONTROLLED ACCEPTANCE FAULT: retry this unchanged case"
                )
            return actual_evaluate(payload)

        with patch.object(integration, "evaluate", one_fault):
            first = run_local(directory, workers=1)
        assert (
            injected and first["failed"] == 1 and first["succeeded"] == len(cases) - 1
        )
        before_retry = read_results(directory, require_success=False)
        assert [row["case_id"] for row in before_retry] == identities
        assert before_retry[0]["status"] == "failed"
        assert "CONTROLLED ACCEPTANCE FAULT" in before_retry[0]["error"]["message"]
        try:
            read_results(directory)
        except ValueError:
            pass
        else:
            raise RuntimeError("Incomplete results were accepted as a complete design")
        try:
            analyse_sensitivity(
                design, metrics_from_rows(before_retry, identities, states)
            )
        except ValueError:
            pass
        else:
            raise RuntimeError("Incomplete sensitivity inputs were accepted")
        retained_attempts = _attempt_count(directory)
        assert run_local(directory)["failed"] == 1
        assert _attempt_count(directory) == retained_attempts
        assert read_results(directory, require_success=False) == before_retry
        assert run_local(directory, retry_failed=True)["succeeded"] == len(cases)
        assert _attempt_count(directory) == retained_attempts + 1
    else:
        assert run_local(directory, workers=1)["succeeded"] == len(cases)

    rows = read_results(directory)
    values = metrics_from_rows(rows, identities, states)
    if before_retry is not None:
        assert rows[0]["id"] != before_retry[0]["id"]
        assert all(rows[i] == before_retry[i] for i in range(1, len(rows)))
    attempts = _attempt_count(directory)
    assert run_local(directory)["succeeded"] == len(cases)
    assert _attempt_count(directory) == attempts
    assert read_results(directory) == rows
    if engine == "energyplus":
        assert cases[0].to_dict()["payload"]["simulation"][
            "settings"
        ] == settings.model_dump(mode="json")
        for row in rows:
            hourly = Evaluation.from_dict(row["result"]).energy.hourly
            assert any(
                name.split("::", 1)[0].upper() == EXTRA_OUTPUT for name in hourly
            )
    result = {
        "engine": engine,
        "design": "independent_uniform_jansen" if design else "grid",
        "plan_id": manifest["id"],
        "case_ids": identities,
        "state_ids": states,
        "rows": len(rows),
        "annual_heating_and_fan_kwh": values,
        "attempts": attempts,
        "resume_extra_attempts": 0,
        "controlled_fault_injection": design is not None,
        "settings_roundtrip": True,
    }
    if design is not None:
        result["sensitivity"] = analyse_sensitivity(design, values)
        assert all(
            math.isfinite(number)
            for indices in result["sensitivity"].values()
            for number in indices.values()
        )
        result["incomplete_sensitivity_rejected"] = True
        result["controlled_failure"] = {
            "index": 0,
            "case_id": identities[0],
            "attempt_id": before_retry[0]["id"],
            "error_type": before_retry[0]["error"]["type"],
            "message": before_retry[0]["error"]["message"],
        }
    return result


def run_cases(directory, energyplus):
    """Run two grid rows and six Jansen rows for each engine using fixed teaching inputs."""
    from epsm_core import CompilerSettings, HourlyOutputRequest
    from epsm_workflows import Parameter, grid, sensitivity_design

    from epsm import Weather

    # This checkout's example fixture imports only installed scientific packages.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "examples"))
    from renovation_case import make_case, rc_settings

    baseline = make_case()["baseline"]
    original = baseline.to_dict()
    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
    grid_samples = grid({PARAMETER: [0.05, 0.15]})
    design = sensitivity_design([Parameter(PARAMETER, 0.05, 0.15)], 2, seed=42)
    results = []
    for engine in ("epsm_rc", "energyplus"):
        settings = (
            rc_settings()
            if engine == "epsm_rc"
            else CompilerSettings(
                hourly_outputs=(HourlyOutputRequest(name=EXTRA_OUTPUT),)
            )
        )
        for name, samples, selected_design in (
            ("grid", grid_samples, None),
            ("jansen", design.samples, design),
        ):
            results.append(
                _run_plan(
                    directory / engine / name,
                    baseline,
                    samples,
                    engine=engine,
                    weather=weather,
                    settings=settings,
                    energyplus=energyplus,
                    design=selected_design,
                )
            )
            assert baseline.to_dict() == original
    return {
        "plans": results,
        "baseline_unchanged": True,
        "energy_boundary": BOUNDARY,
        "sensitivity_accuracy_validated": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--energyplus-exe", type=Path, required=True)
    parser.add_argument("--compatibility-receipt", type=Path, required=True)
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("--require-wheels", action="store_true")
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError(
            "Use a fresh workflow acceptance directory; existing evidence is retained"
        )
    evidence = {
        "format": 1,
        "status": "failed",
        "synthetic_inputs": True,
        "controlled_fault_injection": True,
        "live_services_used": False,
        "wheel_imports_required": args.require_wheels,
    }
    try:
        evidence["energyplus_version"] = require_energyplus(args.energyplus_exe)
        evidence["compatibility_receipt"] = read_workflow_receipt(
            args.compatibility_receipt
        )
        evidence["packages"] = installed_packages(
            evidence["compatibility_receipt"], require_wheels=args.require_wheels
        )
        if args.require_wheels and args.wheels is None:
            raise RuntimeError(
                "Installed checks require the actual built wheel directory"
            )
        if args.wheels is not None:
            wheels = sorted(args.wheels.glob("*.whl"))
            if not wheels:
                raise RuntimeError("No built wheel artifacts supplied")
            evidence["wheels"] = {path.name: sha256(path) for path in wheels}
        evidence["cases"] = run_cases(directory, str(args.energyplus_exe.resolve()))
        evidence["status"] = "passed"
    except Exception as error:
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (directory / "workflow-compatibility-report.json").write_text(
            json.dumps(evidence, indent=2, allow_nan=False) + "\n"
        )
    print(
        f"Passed installed grid/Jansen execution, retry and resume through both engines: {directory}"
    )


if __name__ == "__main__":
    main()
