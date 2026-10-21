# File: src/epsm/requirements.py
# Purpose: Public preparation diagnostics and normalized evaluation output checks.
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# Date created: 2026-10-21
"""Compose owner readiness and check common output boundaries without simulation.

Core and RC retain physical/capability validation. This module owns the common
thermal, delivered-energy and LCA completeness handoff to study execution.
"""

from __future__ import annotations

import math
from subprocess import SubprocessError

DEFAULT_OUTPUTS = (
    {
        "name": "space_heating_demand_kwh",
        "resolution": "hourly",
        "required": True,
        "level": "building",
        "unit": "kWh",
    },
    {
        "name": "delivered_energy",
        "resolution": "annual",
        "required": True,
        "level": "building",
    },
)


def output_requirements(outputs=None):
    """Normalize explicit output descriptors and simple signal-name shortcuts.

    Names default to hourly building signals. ``delivered_energy`` means the
    annual common carrier boundary; ``lca`` means a complete assessment. An
    omitted list requests hourly heating and delivered energy, separately.
    """
    if isinstance(outputs, str):
        outputs = [outputs]
    result = []
    for value in DEFAULT_OUTPUTS if outputs is None else outputs:
        item = {"name": value} if isinstance(value, str) else dict(value)
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Output requirements need a nonempty name")
        item.setdefault(
            "resolution",
            "annual"
            if name == "delivered_energy"
            else "assessment"
            if name == "lca"
            else "hourly",
        )
        item.setdefault("required", True)
        item.setdefault("level", "building")
        if name == "space_heating_demand_kwh":
            item.setdefault("unit", "kWh")
        if item["resolution"] not in {"hourly", "annual", "assessment"}:
            raise ValueError(f"Unsupported output resolution: {item['resolution']}")
        if item["level"] not in {"building", "zone"} or not isinstance(
            item["required"], bool
        ):
            raise ValueError(
                "Output level must be building/zone and required must be boolean"
            )
        if name == "delivered_energy" and item["resolution"] != "annual":
            raise ValueError("delivered_energy requires annual resolution")
        if name == "lca" and item["resolution"] != "assessment":
            raise ValueError("lca requires assessment resolution")
        result.append(item)
    return result


def _issue(diagnostics, code, field, message, required=True):
    diagnostics.append(
        dict(
            code=code,
            field=field,
            message=str(message),
            severity="error" if required else "warning",
        )
    )


def preflight(
    building,
    weather=None,
    engine="energyplus",
    settings=None,
    outputs=None,
    energyplus=None,
):
    """Inspect an explicitly prepared building without running a simulation.

    Parameters
    ----------
    building : epsm_core.Building
        Physical authoring state; never changed.
    weather : epsm_core.Weather or path-like, optional
        Selected EPW. Its content identity and complete calendar are checked.
    engine : {'energyplus', 'epsm_rc'}
        Engine whose owning package supplies capability checks.
    settings : owner settings or dict, optional
        CompilerSettings for EnergyPlus; explicit RCSettings for RC.
    outputs : sequence of dict or str, optional
        Output names, resolution, required flag, level and optional unit.
    energyplus : str or pathlib.Path, optional
        Explicit executable checked through Core's public compiler constructor.
        Its version command and IDD are inspected; no simulation is run. When
        omitted, engine installation is deferred to execution preparation.

    Returns
    -------
    dict
        ``ready`` and structured diagnostics, normalized output requirements
        and effective owner settings where available. LCA input diagnostics do
        not assert that an assessment has already been calculated.
    """
    from epsm_core import Building, CompilerSettings, Weather

    requirements = output_requirements(outputs)
    diagnostics = []
    effective = None
    if engine not in {"energyplus", "epsm_rc"}:
        _issue(
            diagnostics, "unsupported_engine", "engine", f"Unsupported engine: {engine}"
        )
    elif not isinstance(building, Building):
        _issue(
            diagnostics,
            "invalid_input",
            "building",
            "building must be an epsm_core.Building",
        )
    elif engine == "epsm_rc":
        try:
            from epsm_rc import preflight as rc_preflight

            report = rc_preflight(building, weather=weather, settings=settings)
            diagnostics.extend(report["diagnostics"])
            effective = report.get("settings")
        except ImportError as error:
            _issue(
                diagnostics,
                "missing_capability",
                "engine",
                f"Public RC preflight is unavailable: {error}",
            )
    else:
        report = building.readiness(engine=engine, weather=weather)
        for name in report.missing:
            _issue(
                diagnostics, "missing_input", name, f"Required input is missing: {name}"
            )
        for message in report.unsupported:
            _issue(diagnostics, "unsupported_input", "building", message)
        try:
            settings = (
                settings
                if isinstance(settings, CompilerSettings)
                else CompilerSettings.model_validate(settings or {})
            )
            effective = settings.model_dump(mode="json")
            if energyplus is not None:
                from epsm_core import EnergyPlusCompiler

                EnergyPlusCompiler(energyplus, settings=settings)
        except (TypeError, ValueError) as error:
            _issue(diagnostics, "engine_settings", "settings", error)
        except (OSError, SubprocessError) as error:
            _issue(diagnostics, "engine_unavailable", "energyplus", error)
        if weather is None:
            _issue(
                diagnostics,
                "missing_input",
                "weather",
                "Explicit annual weather is required",
            )
        else:
            try:
                selected = (
                    weather
                    if isinstance(weather, Weather)
                    else Weather.from_epw(weather)
                )
                selected.validate()
                if report.ready:
                    building.to_spec(selected)
            except (TypeError, ValueError, OSError) as error:
                _issue(diagnostics, "weather_or_inputs", "weather", error)
    if isinstance(building, Building):
        for item in requirements:
            required, name = item["required"], item["name"]
            if item["level"] == "zone" and engine == "epsm_rc":
                _issue(
                    diagnostics,
                    "unsupported_output",
                    name,
                    "RC does not provide arbitrary per-zone outputs",
                    required,
                )
            if name == "delivered_energy":
                delivery = (
                    building.hvac.delivery.heating
                    if building.hvac is not None
                    else None
                )
                if delivery is None:
                    _issue(
                        diagnostics,
                        "delivery_input",
                        "hvac.delivery.heating",
                        "Explicit heating delivery is required for delivered carrier totals",
                        required,
                    )
                elif (
                    building.hvac.airflow.topology != "S"
                    and delivery.specific_fan_power_w_per_l_s is None
                ):
                    _issue(
                        diagnostics,
                        "delivery_input",
                        "hvac.delivery.heating.specific_fan_power_w_per_l_s",
                        "Mechanical ventilation requires explicit fan accounting",
                        required,
                    )
            elif name == "lca" and getattr(building, "assessment", None) is None:
                _issue(
                    diagnostics,
                    "assessment_input",
                    "assessment",
                    "Explicit assessment settings and factors are required for complete LCA",
                    required,
                )
    return dict(
        ready=not any(row["severity"] == "error" for row in diagnostics),
        engine=engine,
        diagnostics=diagnostics,
        settings=effective,
        outputs=requirements,
    )


def validate_outputs(evaluation, outputs=None):
    """Check retained output coverage, calendars, units and separate completeness.

    Parameters
    ----------
    evaluation : epsm.Evaluation or dict
        Already calculated evaluation. No engine or file access occurs.
    outputs : sequence of dict or str, optional
        Same descriptors as ``preflight``. Missing optional signals produce
        warnings. Thermal, delivered-energy and assessment completeness are
        returned independently, so incomplete LCA cannot hide valid heating.

    Returns
    -------
    dict
        ``ready``, ``thermal_complete``, ``delivery_complete``, ``lca_complete``
        and structured diagnostics. Annual kWh sums use Core's interpretation
        tolerance, relative 0.001 and absolute 1e-6 kWh.
    """
    import numpy as np

    data = evaluation.to_dict() if hasattr(evaluation, "to_dict") else evaluation
    energy, lca = data.get("energy", {}), data.get("lca", {})
    requirements = output_requirements(outputs)
    diagnostics = []
    axis, calendar_ok = energy.get("time_axis", []), False
    try:
        year = data.get("weather", {}).get("calendar_year")
        year = int(year if year is not None else str(axis[0])[:4])
        expected = np.arange(
            f"{year}-01-01", f"{year + 1}-01-01", dtype="datetime64[h]"
        )
        actual = np.asarray(axis, dtype="datetime64[s]")
        calendar_ok = actual.ndim == 1 and np.array_equal(
            actual, expected.astype("datetime64[s]")
        )
    except (ValueError, TypeError, IndexError):
        calendar_ok = False
    hourly, scalars, units = (
        energy.get("hourly", {}),
        energy.get("scalars", {}),
        energy.get("units", {}),
    )

    def signal_errors(item):
        name = item["name"]
        issues = []
        if item.get("level", "building") == "zone" and (
            "::" not in name or not name.upper().startswith("ZONE ")
        ):
            return [
                (
                    "output_level",
                    "Zone requirements need an explicit native Zone variable::zone-name signal",
                )
            ]
        values = (
            hourly.get(name) if item["resolution"] == "hourly" else scalars.get(name)
        )
        if values is None:
            return [("missing_output", f"Missing {item['resolution']} output: {name}")]
        try:
            numbers = np.asarray(values, dtype=float)
            if not np.isfinite(numbers).all():
                issues.append(("nonfinite_output", f"Output is not finite: {name}"))
            if name == "space_heating_demand_kwh" and np.any(numbers < -1e-6):
                issues.append(
                    ("invalid_output", "Space-heating demand cannot be negative")
                )
            if item["resolution"] == "hourly" and (
                numbers.ndim != 1 or len(numbers) != len(axis)
            ):
                issues.append(
                    (
                        "output_length",
                        f"Hourly output does not match calendar length: {name}",
                    )
                )
            expected_unit = item.get("unit")
            if expected_unit is not None and units.get(name) != expected_unit:
                issues.append(
                    (
                        "output_unit",
                        f"Expected {expected_unit} for {name}; found {units.get(name)!r}",
                    )
                )
            if item["resolution"] == "hourly" and units.get(name) == "kWh":
                total = scalars.get(name)
                if (
                    total is None
                    or not math.isfinite(total)
                    or not np.isclose(
                        float(numbers.sum()), total, rtol=0.001, atol=1e-6
                    )
                ):
                    issues.append(
                        (
                            "annual_reconciliation",
                            f"Annual/hourly energy disagreement: {name}",
                        )
                    )
        except (TypeError, ValueError):
            issues.append(("invalid_output", f"Output is not numeric: {name}"))
        return issues

    heating = {
        "name": "space_heating_demand_kwh",
        "resolution": "hourly",
        "unit": "kWh",
    }
    thermal_complete = (
        calendar_ok
        and energy.get("diagnostics", {}).get("accepted", True)
        and not signal_errors(heating)
    )
    carriers = energy.get("delivered_by_carrier", {})
    delivery_complete = (
        bool(carriers)
        and calendar_ok
        and energy.get("annual", False)
        and not energy.get("requirements")
    )
    delivery_complete = delivery_complete and energy.get("diagnostics", {}).get(
        "accepted", True
    )
    try:
        delivery_complete = delivery_complete and all(
            math.isfinite(v) and v >= 0 for v in carriers.values()
        )
    except (TypeError, ValueError):
        delivery_complete = False
    lca_complete = lca.get("status") == "complete" and not lca.get("requirements")
    hourly_requested = any(
        item["resolution"] == "hourly" and item["required"] for item in requirements
    )
    if hourly_requested and not calendar_ok:
        _issue(
            diagnostics,
            "calendar",
            "energy.time_axis",
            "Hourly results must cover the exact selected annual calendar",
        )
    if not energy.get("diagnostics", {}).get("accepted", True):
        _issue(
            diagnostics,
            "engine_rejected",
            "energy.diagnostics",
            "Engine outputs were not accepted",
        )
    for item in requirements:
        name, required = item["name"], item["required"]
        if name == "delivered_energy":
            if not delivery_complete:
                _issue(
                    diagnostics,
                    "delivery_incomplete",
                    "energy",
                    "Delivered carrier energy is incomplete",
                    required,
                )
        elif name == "lca":
            if not lca_complete:
                _issue(
                    diagnostics,
                    "lca_incomplete",
                    "lca",
                    "Assessment is incomplete or failed",
                    required,
                )
        else:
            for code, message in signal_errors(item):
                _issue(diagnostics, code, name, message, required)
    return dict(
        ready=not any(row["severity"] == "error" for row in diagnostics),
        thermal_complete=bool(thermal_complete),
        delivery_complete=bool(delivery_complete),
        lca_complete=bool(lca_complete),
        diagnostics=diagnostics,
        outputs=requirements,
    )
