# SPDX-License-Identifier: MIT
# Copyright (c) 2026 EPSM Development contributors
# License: See LICENSE at the project root.
"""Apply portable Data definitions through Core's public physical interfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping

from epsm_core import HVACSystem, SourceRecord, resolve_operating_profile
from epsm_data import Archetype, archetype_to_dict

from ._logging import context_logger
from .results import _FrozenJSON, encode

logger = context_logger(__name__)


class ArchetypeApplicationReport(_FrozenJSON):
    """Immutable definitions, assignment paths, sources and unresolved requirements.

    ``to_dict`` exports detached portable data. ``summary`` omits the full source
    definition. Construction and inspection perform no I/O or simulation.
    """

    __slots__ = ()

    @classmethod
    def from_dict(cls, data):
        """Restore an application record without catalogue lookup."""
        if data.get("format") != "epsm-archetype-application-1":
            raise ValueError("Unsupported archetype application report format")
        result = cls()
        result._json = encode(data)
        return result

    def to_dict(self):
        """Return a detached, JSON-compatible historical record."""
        return json.loads(self._json)

    def __getattr__(self, name):
        data = self.to_dict()
        if name not in data:
            raise AttributeError(name)
        value = data[name]
        return tuple(value) if isinstance(value, list) else value

    def summary(self):
        """Inspect counts and choices without exporting the physical definition."""
        return {
            key: value for key, value in self.to_dict().items() if key != "definition"
        }

    def __repr__(self):
        return (
            f"ArchetypeApplicationReport(applied={len(self.applied)}, "
            f"replaced={len(self.replaced)}, requirements={len(self.requirements)})"
        )

    __str__ = __repr__


def _source(path, definition):
    identity = getattr(
        definition, "profile_id", getattr(definition, "template_id", None)
    )
    identity = identity or getattr(definition, "archetype_id", "authored-envelope")
    return SourceRecord(
        field_path=path,
        status="assumed",
        source="; ".join(definition.source_references) or identity,
        assumption_profile=identity,
    )


def _area_choice(building, basis, assumptions):
    explicit = building.load_reference_area_m2
    conflicting = any(
        record.field_path == "load_reference_area_m2"
        and record.evidence
        and record.evidence.get("reference_basis", basis) != basis
        for record in building.provenance.records
    )
    if explicit is not None and not conflicting:
        assumptions.append(
            {
                "field": "load_reference_area_m2",
                "value": explicit,
                "interpretation": f"Caller applies {basis}-based inputs to this explicit load-reference area.",
            }
        )
        return True
    if (
        basis == "conditioned_floor_area"
        and not conflicting
        and building.load_reference_area_policy == "conditioned_floor_area"
        and building.geometry is not None
    ):
        return True
    return False


def _leaves(path, value):
    if isinstance(value, Mapping):
        return [
            leaf
            for key, child in value.items()
            for leaf in _leaves(path + "." + str(key), child)
        ]
    if isinstance(value, (tuple, list)) and value:
        return [
            leaf
            for i, child in enumerate(value)
            for leaf in _leaves(path + "." + str(i), child)
        ]
    return [path]


def _preserve_sources(building, section, old, explicit):
    """Narrow existing sources around supplied leaves before section replacement."""
    if old is None:
        return []
    result = []
    for record in building.provenance.records:
        path = record.field_path
        if path != section and not path.startswith(section + "."):
            continue
        value = old
        try:
            for key in path.split(".")[1:]:
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        for leaf in _leaves(path, value):
            if not any(
                leaf == supplied or leaf.startswith(supplied + ".")
                for supplied in explicit
            ):
                result.append(record.updated(field_path=leaf))
    return result


def _covered(path, roots):
    return any(path == root or path.startswith(root + ".") for root in roots)


def _template_paths(values, hvac):
    """Source whole replaced model fields and identify products by resolved order."""
    paths = []
    for section, fields in values.items():
        if section == "equipment":
            continue
        for name, value in fields.items():
            root = f"hvac.{section}.{name}"
            if section == "delivery" and isinstance(value, Mapping):
                # Core retains other heating/FVP fields, but replaces a supplied
                # schedule field completely, including its calendar metadata.
                paths.extend(root + "." + field for field in value)
            else:
                paths.append(root)
    indexes = {record.identifier: i for i, record in enumerate(hvac.equipment)}
    for record in values.get("equipment", ()):
        index = indexes[record["identifier"]]
        paths.extend(f"hvac.equipment.{index}.{field}" for field in record)
        if "product_id" in record and "occurrence_id" not in record:
            paths.append(f"hvac.equipment.{index}.occurrence_id")
    return paths


def apply_archetype(building, archetype, *, mode="replace", calendar=None):
    """Validate supplied definitions, then commit one atomic Core assignment."""
    if not isinstance(archetype, Archetype):
        raise TypeError("archetype must be an EPSM Data Archetype")
    if mode not in {"replace", "fill_missing"}:
        raise ValueError("mode must be 'replace' or 'fill_missing'")
    definition = archetype_to_dict(archetype)
    before = building.snapshot().sha256
    requirements, assumptions, unmatched, retained, records = [], [], [], [], []
    sources = list(archetype.source_references)
    inputs = {"construction_set": archetype.construction_set, "mode": mode}
    profile = archetype.operating_profile
    profile_airflow, profile_sources = {}, []
    profile_defines_use = False
    operation_needed = mode == "replace" or building.operation is None
    hvac_needed = mode == "replace" or building.hvac is None
    if profile is not None:
        resolved = resolve_operating_profile(
            profile, calendar=calendar, previous=building.operation
        )
        sources.extend(profile.source_references)
        values = resolved.assumptions
        custom = profile.values.get("building_assumptions")
        profile_defines_use = custom is None or "use" in custom
        if operation_needed and profile_defines_use:
            inputs["operation"] = resolved.operation
            if resolved.operation is None:
                requirements.extend(
                    "operating_profile." + item
                    for item in resolved.requirements
                    if item.startswith("use.") or item in {"calendar", "operation"}
                )
            if (
                "load_reference_area_m2" in resolved.requirements
                or "load_reference_area_m2" in profile.values.get("requirements", ())
            ):
                basis = (
                    "load_reference_area"
                    if profile.values.get("profile_id") == "epsm.generic_other.v1"
                    else "Atemp"
                )
                if not _area_choice(building, basis, assumptions):
                    requirements.append(
                        f"operating_profile.load_reference_area_m2 ({basis})"
                    )
        elif profile_defines_use:
            retained.append("operation")
        profile_airflow = dict(values.get("airflow", {}))
        if "topology" in profile_airflow:
            unmatched.append(
                "operating_profile.airflow.topology (select an HVAC template)"
            )
            profile_airflow.pop("topology")
        facade = dict(values.get("facade", {}))
        properties = {
            key: value
            for key, value in facade.items()
            if key in {"glazing", "solar_shading_factor"}
        }
        if properties:
            inputs["facade_properties"] = properties
        unmatched.extend(
            "operating_profile.facade." + key for key in facade if key not in properties
        )
        if "common_use" in values:
            unmatched.append(
                "operating_profile.common_use (whole-building application)"
            )
            if (
                building.geometry is not None
                and building.geometry.zoning.mode == "apartments"
            ):
                requirements.append(
                    "operating_profile.common_use requires targeted common-space assignment"
                )
        for record in resolved.source_records:
            path = record.field_path
            head, dot, tail = path.partition(".")
            owner = {
                "use": "operation",
                "airflow": "hvac.airflow",
                "facade": "facade",
            }.get(head)
            if owner is not None:
                adjusted = record.updated(
                    field_path=owner + (dot + tail if dot else "")
                )
                if head == "airflow" and not dot:
                    profile_sources.extend(
                        adjusted.updated(field_path=leaf)
                        for leaf in _leaves("hvac.airflow", profile_airflow)
                    )
                else:
                    (profile_sources if head == "airflow" else records).append(adjusted)
        if (
            operation_needed
            and resolved.operation is not None
            and (
                custom is not None or profile.values.get("purpose") == "epc_normal_use"
            )
        ):
            explicit = [
                r.field_path
                for r in records
                if r.field_path == "operation" or r.field_path.startswith("operation.")
            ]
            records.extend(
                _preserve_sources(
                    building,
                    "operation",
                    building.operation.model_dump(mode="json")
                    if building.operation is not None
                    else None,
                    explicit,
                )
            )
    envelope = archetype.envelope_performance
    envelope_airflow = {}
    if envelope is not None:
        sources.extend(envelope.source_references)
        if envelope.thermal_bridge_delta_u_w_m2k is not None:
            inputs["thermal_bridge_delta_u_w_m2k"] = envelope.thermal_bridge_delta_u_w_m2k
        else:
            inputs["thermal_bridge_uplift_fraction"] = (
                envelope.thermal_bridge_uplift_fraction
            )
        rate, area_rate, basis = (
            envelope.infiltration_ach,
            envelope.infiltration_l_s_m2,
            envelope.infiltration_reference_basis,
        )
        airflow_needed = mode == "replace" or building.hvac is None
        if not airflow_needed and (rate is not None or area_rate is not None):
            retained.append(
                "hvac.airflow."
                + (
                    "envelope_infiltration_l_s_m2"
                    if area_rate is not None
                    else "envelope_infiltration_ach"
                )
            )
        elif rate is not None:
            if basis == "conditioned_volume":
                envelope_airflow = {
                    "envelope_infiltration_ach": rate,
                    "envelope_infiltration_l_s_m2": None,
                }
            else:
                requirements.append(
                    "envelope_performance.infiltration_reference_volume_conversion"
                )
        elif area_rate is not None:
            if _area_choice(building, basis, assumptions):
                envelope_airflow = {
                    "envelope_infiltration_ach": 0.0,
                    "envelope_infiltration_l_s_m2": area_rate,
                }
            else:
                requirements.append(
                    f"envelope_performance.load_reference_area ({basis})"
                )
        for name in ("thermal_bridge_uplift_fraction", "thermal_bridge_delta_u_w_m2k"):
            if getattr(envelope, name) is not None:
                records.append(_source(name, envelope))
    template = archetype.hvac_template
    template_airflow = {}
    if template is not None:
        sources.extend(template.source_references)
        template_values = template.to_dict()["values"]
        template_airflow = template_values.get("airflow", {})
        # Validate the selected template independently even when fill retains it.
        supplied = HVACSystem.resolve_template(template, previous=building.hvac)
        if hvac_needed:
            composed = dict(template_values)
            composed["airflow"] = {
                **profile_airflow,
                **template_airflow,
                **envelope_airflow,
            }
            resolution = HVACSystem.resolve_template(
                template.with_changes(values=composed), previous=building.hvac
            )
            if resolution.hvac is None:
                requirements.extend(
                    "hvac_template." + item for item in resolution.requirements
                )
            elif _leaves("hvac", template_values):
                inputs["hvac"] = resolution.hvac
                # Preserve inherited evidence; source precedence is profile < template < envelope.
                explicit = _template_paths(template_values, resolution.hvac)
                changed = (
                    list(explicit)
                    + ["hvac.airflow." + key for key in profile_airflow]
                    + ["hvac.airflow." + key for key in envelope_airflow]
                )
                records.extend(
                    _preserve_sources(
                        building,
                        "hvac",
                        building.hvac.to_dict() if building.hvac is not None else None,
                        changed,
                    )
                )
                records.extend(
                    _source(path, template)
                    for path in explicit
                    if not _covered(
                        path, ("hvac.airflow." + key for key in envelope_airflow)
                    )
                )
        else:
            retained.append("hvac")
        del supplied
    # Existing installed topology is retained for profile/envelope-only updates.
    patch = {**profile_airflow, **envelope_airflow}
    if inputs.get("hvac") is not None:
        # Already composed before typed construction; source the actual supplied leaves.
        profile_sources = [
            record
            for record in profile_sources
            if not _covered(
                record.field_path,
                (
                    "hvac.airflow." + key
                    for key in (*template_airflow, *envelope_airflow)
                ),
            )
        ]
    elif patch:
        inputs["airflow_properties"] = patch
    records.extend(
        record
        for record in profile_sources
        if not _covered(
            record.field_path, ("hvac.airflow." + key for key in envelope_airflow)
        )
    )
    records.extend(_source("hvac.airflow." + key, envelope) for key in envelope_airflow)
    if archetype.construction_set is not None:
        records.append(_source("construction_set", archetype))
    inputs["provenance"] = {"records": records}
    assignment = building.assign_inputs(**inputs)
    readiness = building.readiness()
    requirements.extend((*readiness.missing, *readiness.unsupported))
    report = ArchetypeApplicationReport.from_dict(
        {
            "format": "epsm-archetype-application-1",
            "archetype_id": archetype.archetype_id,
            "mode": mode,
            "definition": definition,
            "before_state_id": before,
            "after_state_id": building.snapshot().sha256,
            **assignment.to_dict(),
            "retained": list(dict.fromkeys((*assignment.retained, *retained))),
            "unmatched": list(dict.fromkeys((*assignment.unmatched, *unmatched))),
            "requirements": list(dict.fromkeys(requirements)),
            "sources": list(dict.fromkeys(sources)),
            "assumptions": assumptions,
        }
    )
    building._archetype_applications = (*building.archetype_applications, report)
    logger.info(
        "Applied archetype %s to %s",
        archetype.archetype_id,
        building.identifier,
        extra={
            "epsm_event": "building.archetype.applied",
            "epsm_context": {
                "building_id": building.identifier,
                "archetype_id": archetype.archetype_id,
            },
        },
    )
    return report
