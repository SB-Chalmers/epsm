# SPDX-License-Identifier: MIT
"""Candidate dispatches use exact immutable cohorts and retain ordinary gates."""

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_platform_workflow_parses_and_candidate_source_is_explicit():
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    # YAML 1.1 treats the Actions keyword `on` as true.
    events = workflow.get("on", workflow.get(True))
    candidate = events["workflow_dispatch"]["inputs"]["candidate_manifest_revision"]
    assert candidate["type"] == "string" and candidate["default"] == ""
    combination = workflow["jobs"]["combination"]
    matrix = next(step for step in combination["steps"] if step.get("id") == "matrix")
    assert "--candidate-revision" in matrix["run"]
    assert "--consumer-revision" in matrix["run"]
    platform = workflow["jobs"]["platform"]
    assert any(
        "check_study_platform.py" in step.get("run", "") for step in platform["steps"]
    )
    assert any(
        "check_workflow_handoff.py" in step.get("run", "") for step in platform["steps"]
    )
    assert any(
        "check_archetype_handoff.py" in step.get("run", "")
        for step in platform["steps"]
    )


def test_embedded_display_matrix_python_is_valid():
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    display = next(
        step
        for step in workflow["jobs"]["combination"]["steps"]
        if step.get("id") == "display"
    )
    script = display["run"].split("\n", 1)[1].rsplit("PYTHON", 1)[0]
    ast.parse(script)
