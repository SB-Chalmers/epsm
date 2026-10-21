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
    assert set(events) == {"workflow_dispatch"}
    assert "inputs.candidate_manifest_revision" in workflow["env"]["CANDIDATE_REVISION"]
    assert "vars." not in workflow["env"]["CANDIDATE_REVISION"]
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


def test_display_receipt_uses_the_same_explicit_manifest_as_scientific_checks():
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    display = workflow["jobs"]["display"]
    selection = workflow["jobs"]["platform"]["env"]["PLATFORM_MANIFEST"]
    assert display.get("env", {}).get("PLATFORM_MANIFEST") == selection
    handoff = next(
        step
        for step in display["steps"]
        if "check_viewer_handoff.py" in step.get("run", "")
    )
    assert '--manifest "$PLATFORM_MANIFEST"' in handoff["run"]


def test_main_metadata_checkout_retains_actual_remote_main_for_detached_prs():
    workflow = yaml.safe_load((ROOT / ".github/workflows/metadata.yml").read_text())
    checkout = workflow["jobs"]["metadata"]["steps"][0]
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"].get("fetch-depth") == 0
    assert checkout["with"].get("persist-credentials") is False
