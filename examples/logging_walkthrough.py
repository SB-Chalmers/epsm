# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Trace real catalogue → portable record → Building → RC → LCA handoffs.

Uses synthetic evidence, the packaged teaching weather and a real annual RC
calculation. No live database or provider access is required. Logs describe
execution; evaluation artifacts and diagnostics establish the outcome.
"""

import json
from importlib.resources import files
from pathlib import Path

from epsm_data import Catalogue
from epsm_db import BuildingRecord, BuildingType, Stock, StockCell
from renovation_case import make_case, rc_settings

from epsm import Weather, configure_logging, reset_logging


def run(directory):
    """Write a retained offline trace and return the complete evaluation."""
    directory = Path(directory)
    configure_logging(directory=directory)
    context = {"study_id": "logging-walkthrough"}
    try:
        Catalogue.load(log_context=context)
        case = make_case()
        template = case["baseline"]
        footprint = template.geometry.parts[0].footprint.polygon
        record = BuildingRecord(
            "synthetic-logging-release",
            "logging-building",
            BuildingType("multi_family"),
            footprint,
            {"construction_year": 1960},
            components=({"component_id": "part", "geometry": footprint},),
            heights=({"component_id": "part", "height_m": 8.4},),
        )

        class OfflineCell(StockCell):
            def iter_records(self, *, batch_size=100):
                yield record

        from types import SimpleNamespace

        stock = Stock(SimpleNamespace(dataset_id=record.dataset_id))
        cell = OfflineCell(stock, "multi_family", "SE.02")
        physical = {
            name: getattr(template, name)
            for name in (
                "construction_set",
                "facade",
                "hvac",
                "operation",
                "foundation",
                "thermal_bridge_uplift_fraction",
                "load_reference_area_policy",
            )
        }
        models, receipts = cell.to_epsm(
            storeys=3, storey_height_m=2.8, log_context=context, **physical
        )
        assert len(models) == 1 and not receipts[0].errors
        building = models[0]
        building.assessment = case["settings"]
        weather = Weather.from_epw(files("epsm_rc") / "data/epw/goteborg.epw")
        result = building.simulate(
            engine="epsm_rc",
            weather=weather,
            directory=directory / "runs",
            settings=rc_settings(),
            log_context=context,
        )
        assert result.energy.complete
    finally:
        reset_logging()
    records = [
        json.loads(line)
        for line in (directory / "logs/study.jsonl").read_text().splitlines()
    ]
    assert any(record["logger"].startswith("epsm_db") for record in records)
    assert any(record["event"] == "energy.rc.completed" for record in records)
    assert any(record["event"] == "lca.assessment.completed" for record in records)
    starts = {
        r["context"]["operation_id"]: r
        for r in records
        if r["event"].endswith(".started") and "context" in r
    }
    for record in starts.values():
        parent = record["context"].get("parent_operation_id")
        if parent:
            assert parent in starts
    assert any(r["event"] == "evaluation.saved" for r in records)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    print(run(parser.parse_args().directory).id)
