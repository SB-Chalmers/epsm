# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Require a portable six-evaluation study using actual RC and EnergyPlus 24.2.

One illustrative building, a frozen baseline and two material-backed renovation
alternatives exercise the public Study, Workflow and StudyResults interfaces.
The shared teaching fixture defines assumptions and factors. No measured-building
validation or agreement threshold between engines is implied. Missing required
inputs fail and remain visible in the retained report.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import runpy
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from importlib import metadata
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("epsm", "epsm_core", "epsm_data", "epsm_rc", "epsm_lca",
            "epsm_workflows", "epsm_studies")
SIGNAL = "space_heating_demand_kwh"
YEAR = 2023
OUTPUTS = [
    {"name": SIGNAL, "resolution": "hourly", "unit": "kWh", "required": True},
    {"name": "delivered_energy", "resolution": "annual", "required": True},
    {"name": "lca", "resolution": "assessment", "required": True},
]


def intended_calendar():
    """Create the intended nonleap annual calendar independently of engine output."""
    start, end = datetime(YEAR, 1, 1), datetime(YEAR + 1, 1, 1)
    return [(start + timedelta(hours=hour)).isoformat()
            for hour in range(int((end - start).total_seconds() / 3600))]


def build_study(energyplus):
    """Author the common teaching case through public package interfaces."""
    from epsm_studies import Study

    from epsm import Weather

    fixture = runpy.run_path(str(ROOT / "examples/renovation_case.py"))
    case = fixture["make_case"]()
    before = case["baseline"].to_dict()
    weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw",
                               calendar_year=YEAR)
    study = Study("portable-renovation-engine-check", method="comparative",
                  question="Do study contracts retain complete paired evaluations?",
                  protocol={"synthetic_inputs": True, "calendar_year": YEAR,
                            "interpretation": "software handoff; not measured-building validation"})
    study.add_subject(case["baseline"], id="one")
    study.add_scenario("windows", case["step_1"], subject="one")
    study.add_scenario("windows-and-insulation", case["step_2"], subject="one")
    study.add_weather(weather, id="goteborg-2023", subjects=["one"])
    study.set("engines", ["epsm_rc", "energyplus"])
    study.set("engine_settings", {
        "epsm_rc": {"settings": asdict(fixture["rc_settings"]())},
        "energyplus": {"energyplus": str(energyplus)},
    })
    study.set("outputs", OUTPUTS)
    if case["baseline"].to_dict() != before:
        raise RuntimeError("Authoring alternatives changed the baseline")
    return study


def reopen_without_execution(archive, *, require_wheels):
    """Verify a relocated archive in a new process with execution imports blocked."""
    program = """
import importlib.abc, json, sys
blocked = {'epsm', 'epsm_workflows', 'epsm_core', 'epsm_rc', 'epsm_lca'}
class RejectExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in blocked:
            raise ImportError('Execution dependency forbidden while reopening: ' + fullname)
sys.meta_path.insert(0, RejectExecution())
from epsm_studies import Study, StudyResults
results = StudyResults.open(sys.argv[1])
assert Study.open(sys.argv[1]).id == results.spec.id
verified = results.verify()
assert results.coverage()['complete'] and results.coverage()['total'] == 6
assert all(len(results.hourly(row['case_id'])) == 8760 for row in results.table())
assert not blocked.intersection(name.split('.')[0] for name in sys.modules)
print(json.dumps({'archive_id': results.id, 'coverage': results.coverage(),
                  'verification': verified, 'execution_imports_used': False}))
"""
    command = [sys.executable, *( ["-I"] if require_wheels else []), "-c", program, str(archive)]
    result = subprocess.run(command, cwd=archive.parent, check=True, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    return json.loads(result.stdout)


def run_cases(directory, energyplus, *, require_wheels):
    """Run six frozen cases, inspect both comparisons and reopen retained results."""
    from epsm_studies import StudyResults

    study = build_study(energyplus)
    study.save(directory / "study.json")
    preview = study.preview()
    if not preview["ready"] or preview["case_count"] != 6:
        raise RuntimeError(f"Expected six ready paired evaluations: {preview['diagnostics']}")
    states = {(row["axes"]["scenario_id"], row["axes"]["engine"]): row["state_id"]
              for row in preview["cases"]}
    for scenario in ("baseline", "windows", "windows-and-insulation"):
        if states[(scenario, "epsm_rc")] != states[(scenario, "energyplus")]:
            raise RuntimeError("Paired engines do not share a physical state")
    if len({state for (scenario, engine), state in states.items() if engine == "epsm_rc"}) != 3:
        raise RuntimeError("Renovation alternatives lost their independent physical states")
    execution = directory / "execution"
    plan = study.prepare(execution)
    outcome = study.run(execution, workers=1)
    results = study.archive(execution, directory / "archive")
    coverage = results.coverage()
    if not coverage["complete"] or coverage["succeeded"] != 6:
        raise RuntimeError(f"Required retained study results are incomplete: {coverage}")
    if len(results.attempts()) != 6:
        raise RuntimeError("Expected one retained successful attempt per evaluation")
    before = results.attempts()
    resumed = study.run(execution, workers=1)
    resumed_results = study.archive(execution, directory / "archive")
    if resumed != outcome or resumed_results.attempts() != before:
        raise RuntimeError("Resuming completed work changed retained outcomes")
    rows = results.table()
    retained = []
    for row in rows:
        case_id = row["case_id"]
        metadata_value = results.evaluation_metadata(case_id)
        observed_calendar = [datetime.fromisoformat(str(value)).isoformat()
                             for value in results.time_axis(case_id)]
        if len(results.hourly(case_id)) != 8760 or observed_calendar != intended_calendar():
            raise RuntimeError("Hourly heating lost the intended annual calendar")
        assessment = metadata_value["lca"]
        contributions = assessment.get("contributions", [])
        if assessment.get("material_gwp_kgco2e") is None or not any(
                item.get("module") != "B6" for item in contributions):
            raise RuntimeError("Embodied impacts or their contributions were omitted")
        monthly = results.aggregate_energy(case_id)
        if len(monthly) != 12 or not math.isclose(
                math.fsum(monthly.values()), row["metrics"][SIGNAL], rel_tol=0.001, abs_tol=0.001):
            raise RuntimeError("Retained monthly heating does not reconcile to annual heating")
        retained.append({"case_id": case_id, "axes": row["axes"],
                         "evaluation_id": row["evaluation_id"],
                         "annual_heating_kwh": row["metrics"][SIGNAL],
                         "material_gwp_kgco2e": assessment["material_gwp_kgco2e"],
                         "assessment_contributions": len(contributions)})
    comparisons, changes = {}, {}
    for scenario in ("baseline", "windows", "windows-and-insulation"):
        paired = {engine: results.select(scenario_id=scenario, engine=engine)[0]["case_id"]
                  for engine in ("epsm_rc", "energyplus")}
        comparison = results.compare_engines(paired["epsm_rc"], paired["energyplus"],
                                              expected_time_axis=intended_calendar())
        comparisons[scenario] = {key: value for key, value in comparison.items() if key != "hourly"}
    for engine in ("epsm_rc", "energyplus"):
        baseline = results.select(scenario_id="baseline", engine=engine)[0]["case_id"]
        changes[engine] = {}
        for scenario in ("windows", "windows-and-insulation"):
            candidate = results.select(scenario_id=scenario, engine=engine)[0]["case_id"]
            delta = results.difference(baseline, candidate, SIGNAL)
            if not delta["complete"]:
                raise RuntimeError("Baseline comparison has incomplete retained coverage")
            changes[engine][scenario] = delta
    results.export(directory / "results.csv")
    relocated = directory / "relocated" / "archive"
    shutil.copytree(results.directory, relocated)
    reopened = StudyResults.open(relocated)
    if reopened.id != results.id or reopened.table() != rows:
        raise RuntimeError("Relocation changed the retained study identity or case index")
    portability = reopen_without_execution(relocated, require_wheels=require_wheels)
    if portability["archive_id"] != results.id:
        raise RuntimeError("Fresh-process reopening changed the archive identity")
    return {"study_id": study.id, "plan_id": plan["id"], "archive_id": results.id,
            "coverage": coverage, "evaluations": retained, "engine_comparisons": comparisons,
            "baseline_changes": changes, "portable_reopen": portability}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--energyplus-exe", type=Path,
                        default=os.environ.get("ENERGYPLUS_EXE") or shutil.which("energyplus"))
    parser.add_argument("--compatibility-receipt", type=Path)
    parser.add_argument("--wheels", type=Path)
    parser.add_argument("--require-wheels", action="store_true")
    args = parser.parse_args(argv)
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError("Use a fresh study acceptance directory; earlier evidence is retained")
    evidence = {"format": 1, "status": "failed", "planned_evaluations": 6,
                "synthetic_inputs": True, "live_services_used": False,
                "wheel_imports_required": args.require_wheels}
    helpers = runpy.run_path(str(ROOT / "scripts/check_archetype_handoff.py"))
    try:
        if args.energyplus_exe is None:
            raise RuntimeError("EnergyPlus prerequisite missing: set ENERGYPLUS_EXE or --energyplus-exe")
        energyplus = args.energyplus_exe.resolve()
        evidence["energyplus"] = {"path": str(energyplus),
            "version": helpers["require_energyplus"](energyplus), "sha256": helpers["sha256"](energyplus)}
        if args.compatibility_receipt is not None:
            receipt = helpers["read_receipt"](args.compatibility_receipt)
            if not set(PACKAGES) <= receipt["packages"].keys():
                raise RuntimeError("Required study collaborators are absent from the source receipt")
            evidence["packages"] = helpers["installed_packages"](receipt, require_wheels=args.require_wheels)
            evidence["source_receipt_sha256"] = helpers["sha256"](args.compatibility_receipt)
        elif args.require_wheels:
            raise RuntimeError("Installed study checks require --compatibility-receipt with exact source identities")
        else:
            evidence["packages"] = {name: {"version": metadata.version(name),
                "import_path": str(Path(importlib.import_module(name).__file__).resolve()),
                "source_revision": "unverified"} for name in PACKAGES}
        if args.wheels is not None:
            artifacts = sorted(args.wheels.glob("*.whl"))
            if not artifacts:
                raise RuntimeError("No built candidate wheel artifacts supplied")
            evidence["wheels"] = {path.name: helpers["sha256"](path) for path in artifacts}
        elif args.require_wheels:
            raise RuntimeError("Installed study checks require --wheels with actual built artifacts")
        evidence["study"] = run_cases(directory, str(energyplus), require_wheels=args.require_wheels)
        evidence["status"] = "passed"
    except Exception as error:
        evidence["failure"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        (directory / "study-compatibility-report.json").write_text(
            json.dumps(evidence, indent=2, allow_nan=False) + "\n")
    print(f"Passed six paired evaluations and portable study reopening: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
