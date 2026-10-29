"""Optional EPSM assembly. Source records are never changed by completion rules."""

from __future__ import annotations

import importlib
import importlib.metadata
import math
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from epsm_db.enums import BuildingType
from epsm_db.records import (
    BuildingRecord,
    Receipt,
    implementation_hash,
    json_default,
)
from epsm_db.weather import WeatherReference


@dataclass(frozen=True)
class ModelPolicy:
    name: str = "ubem_v1"
    version: str = "4"
    minimum_programme_blend_share: float = 0.05
    typical_floor_height_m: float = 3.0
    minimum_full_floor_height_m: float = 2.0
    maximum_full_floor_height_m: float = 5.0
    basement_depth_m: float = 2.5
    basement_setpoint_c: float = 18.0
    default_roof_pitch_deg: float = 30.0
    minimum_pitched_rise_m: float = 0.1
    maximum_component_overlap_m2: float = 0.25
    maximum_component_overlap_fraction: float = 0.01
    minimum_component_area_m2: float = 5.0
    maximum_component_omission_fraction: float = 0.01
    attic_outdoor_air_ach: float = 0.5
    ftx_recovery: float = 0.7
    heat_pump_cop: float = 3.0
    fuel_efficiency: float = 0.9
    calendar_year: int = 2023
    catalogue_climate_zone: str = "SE.Zone3"
    # Version 4: catalogue ventilation templates and facade window ratios. False
    # restores version 3's type defaults below (one WWR and one FTX recovery).
    catalogue_templates: bool = True
    wwr_by_type: dict = field(
        default_factory=lambda: {
            "single_family": 0.2,
            "multi_family": 0.2,
            "office": 0.2,
            "school": 0.2,
        }
    )
    ventilation_by_type: dict = field(
        default_factory=lambda: {
            "single_family": "S",
            "multi_family": "F",
            "office": "FTX",
            "school": "FTX",
        }
    )

    def __post_init__(self):
        if (
            not math.isfinite(self.minimum_programme_blend_share)
            or not 0 <= self.minimum_programme_blend_share < 1
        ):
            raise ValueError("Minimum programme blend share must lie in [0,1)")
        positive = [
            self.typical_floor_height_m,
            self.minimum_full_floor_height_m,
            self.maximum_full_floor_height_m,
            self.basement_depth_m,
            self.heat_pump_cop,
        ]
        if any(not math.isfinite(x) or x <= 0 for x in positive):
            raise ValueError("Height, depth and COP assumptions must be finite and positive")
        if self.minimum_full_floor_height_m >= self.maximum_full_floor_height_m:
            raise ValueError("Floor-height bounds must increase")
        if not 0 <= self.ftx_recovery <= 1 or not 0 < self.fuel_efficiency <= 1:
            raise ValueError("Invalid recovery or efficiency")
        if not math.isfinite(self.attic_outdoor_air_ach) or self.attic_outdoor_air_ach < 0:
            raise ValueError("Attic exchange must be finite and nonnegative")
        if not 0 < self.default_roof_pitch_deg < 80:
            raise ValueError("Roof pitch must be between 0 and 80 degrees")
        if not math.isfinite(self.minimum_pitched_rise_m) or self.minimum_pitched_rise_m <= 0:
            raise ValueError("Minimum pitched rise must be positive")
        if not math.isfinite(self.maximum_component_overlap_m2) or self.maximum_component_overlap_m2 <= 0:
            raise ValueError("Maximum component overlap area must be positive")
        if not 0 < self.maximum_component_overlap_fraction < 1:
            raise ValueError("Maximum component overlap fraction must be between 0 and 1")
        if not math.isfinite(self.minimum_component_area_m2) or self.minimum_component_area_m2 <= 0:
            raise ValueError("Minimum component area must be finite and positive")
        if not 0 < self.maximum_component_omission_fraction < 1:
            raise ValueError("Maximum component omission fraction must be between 0 and 1")
        if any(not 0 <= x < 1 for x in self.wwr_by_type.values()):
            raise ValueError("WWR must be between 0 and 1")
        if any(x not in {"S", "F", "FT", "FTX"} for x in self.ventilation_by_type.values()):
            raise ValueError("Unsupported ventilation default")


class ModelAssemblyError(ValueError):
    def __init__(self, message, receipt):
        self.receipt = receipt
        super().__init__(message)


def _positive(value):
    return value is not None and math.isfinite(float(value)) and float(value) > 0


# GIS-lake records (epsm_db schema 2) name status and height evidence differently
# from the earlier sweden_ubem database; assembly reads both.
def _lake_record(record):
    return "geometry_valid" in record.facts


def _verified_existing(record):
    if _lake_record(record):
        return record.facts.get("object_status") == "Gällande"
    return bool(record.facts.get("status_verified") and record.facts.get("is_existing"))


def _geometry_resolved(record):
    if _lake_record(record):
        return record.facts.get("geometry_valid") is True
    return record.facts.get("geometry_status") == "resolved"


def _height_evidence(record, component, height):
    """Whether a determined height belongs to this component's geometry, and its resolution."""
    if not height or height.get("height_status") != "determined":
        return False, None
    if _lake_record(record):
        # Lake heights are keyed to their component; the evidence states whether
        # it was measured on that same geometry.
        status = (height.get("attributes") or {}).get("geometry_status")
        return True, "resolved" if status == "consistent_source_component" else status
    return (
        height.get("input_geometry_hash") == component.get("geometry_hash"),
        (height.get("details") or {}).get("evidence_resolution"),
    )


def _field(receipt, name, value, state, assumption=None):
    receipt.fields.setdefault(name, {})
    receipt.fields[name].update(model_value=value, model_state=state)
    if assumption:
        receipt.assumptions.append(assumption)


def _active_dates(year, count, *, school=False):
    current = date(year, 1, 1)
    weekdays = []
    while current.year == year:
        closed = school and (6, 24) <= (current.month, current.day) <= (8, 4)
        if current.weekday() < 5 and not closed:
            weekdays.append(current.isoformat())
        current += timedelta(days=1)
    if len(weekdays) < count:
        raise ValueError("Not enough weekdays for the normal-use calendar")
    return tuple(weekdays[round(i * (len(weekdays) - 1) / (count - 1))] for i in range(count))


def _effective_programme_shares(shares, *, primary, minimum_share, receipt):
    """Assign sub-threshold EPC area to the largest retained operational use."""
    retained = {name: share for name, share in shares.items() if share >= minimum_share}
    if not retained:
        name = max(shares, key=shares.get)
        retained = {name: shares[name]}
    dominant = max(retained, key=lambda name: (retained[name], name == primary))
    omitted = {name: share for name, share in shares.items() if name not in retained}
    retained[dominant] += math.fsum(omitted.values())
    receipt.identities["programme_allocation"] = {
        "reported_shares": dict(shares),
        "modelled_shares": dict(retained),
        "minimum_blend_share": minimum_share,
        "folded_into": dominant if omitted else None,
        "folded_shares": omitted,
    }
    if omitted:
        receipt.assumptions.append(
            f"EPC programme shares below {minimum_share:.0%} folded into {dominant}: "
            + ", ".join(f"{name} {share:.0%}" for name, share in omitted.items())
        )
    return retained


def _ventilation(record, policy, receipt, override):
    if override:
        if override not in {"S", "F", "FT", "FTX"}:
            raise ValueError("Ventilation must be S, F, FT or FTX")
        _field(receipt, "ventilation", override, "assumed", "Caller-supplied ventilation topology")
        return override
    cert = record.selected_certificate if record.single_building_epc else None
    positive = set()
    for name, kind in {
        "VentTypSjalvdrag": "S",
        "VentTypF": "F",
        "VentTypFmed": "Fmed",
        "VentTypFT": "FT",
        "VentTypFTX": "FTX",
    }.items():
        values = [
            o["raw_values"]
            for o in record.observations
            if cert and o["certificate_id"] == cert["certificate_id"] and o["source_field"] == name
        ]
        if (
            len(values) == 1
            and len(values[0]) == 1
            and str(values[0][0]).strip().casefold() in {"ja", "true", "1"}
        ):
            positive.add(kind)
    if positive == {"F", "Fmed"}:
        positive = {"Fmed"}  # exhaust, with recovery
    if len(positive) == 1:
        result = positive.pop()
        if result == "Fmed":
            # Exhaust with heat recovery, in practice an exhaust-air heat pump. With heat-pump
            # heating the exhaust air is the pump's source and its COP carries the recovery,
            # so the building is modelled as F. Otherwise the pump's electricity is not in the
            # heating carrier and the recovered heat lowers it: modelled as recovery on the
            # exhaust flow, FTX at the catalogue's observed-FTX effectiveness.
            result = "F" if _heating_carriers(record) == ["heat_pump"] else "FTX"
            receipt.assumptions.append(
                f"EPC ventilation F with heat recovery modelled as {result}: "
                + ("recovery carried by the heat pump's COP" if result == "F" else "no heat-pump heating carrier")
            )
        _field(receipt, "ventilation", result, "reported_raw_mapping")
    else:
        result = policy.ventilation_by_type[record.type.value]
        _field(
            receipt,
            "ventilation",
            result,
            "assumed",
            f"Ventilation {'conflicting' if positive else 'unavailable'}; type default {result}",
        )
    return result


def _resolve_component_overlaps(parts, policy, receipt):
    """Give tiny prepared-plan overlaps to the larger source component."""
    from epsm_core import Footprint, RoofSpec
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    polygons = [part.footprint.polygon for part in parts]
    ordered = sorted(
        enumerate(parts),
        key=lambda entry: (-entry[1].footprint.area_m2, entry[1].identifier),
    )
    resolved = list(parts)
    owned = []
    changes = []
    for index, part in ordered:
        polygon = polygons[index]
        claimed = unary_union(owned) if owned else None
        overlap = polygon.intersection(claimed).area if claimed is not None else 0.0
        if overlap > 1e-8:
            if (
                overlap > policy.maximum_component_overlap_m2
                or overlap / polygon.area > policy.maximum_component_overlap_fraction
            ):
                raise ValueError(
                    f"Component {part.identifier} overlap {overlap:.6f} m2 exceeds "
                    "bounded ownership repair; source geometry review required"
                )
            trimmed = polygon.difference(claimed)
            edges = list(trimmed.exterior.coords) if trimmed.geom_type == "Polygon" else []
            if edges and min(
                LineString((edges[j], edges[j + 1])).length
                for j in range(len(edges) - 1)
            ) < 0.01001:
                # A microscopic overlap can split an otherwise long edge into a
                # sub-engine-length segment. Move that boundary 15 mm away and
                # simplify only this smaller claimant, preserving the source.
                overlapping_owners = unary_union(
                    [owner for owner in owned if polygon.intersection(owner).area > 1e-8]
                )
                trimmed = polygon.difference(overlapping_owners.buffer(0.015)).simplify(
                    0.005, preserve_topology=True
                )
            if trimmed.geom_type != "Polygon" or trimmed.is_empty or not trimmed.is_valid:
                raise ValueError(
                    f"Component {part.identifier} overlap repair split or invalidated its footprint"
                )
            changed = polygon.symmetric_difference(trimmed).area
            if (
                changed > policy.maximum_component_overlap_m2
                or changed / polygon.area > policy.maximum_component_overlap_fraction
                or trimmed.intersection(claimed).area > 1e-8
            ):
                raise ValueError(
                    f"Component {part.identifier} bounded sliver repair exceeds area or ownership limits"
                )
            changes.append(
                {
                    "component": part.identifier,
                    "source_prepared_area_m2": polygon.area,
                    "removed_overlap_m2": overlap,
                    "total_plan_change_m2": changed,
                    "resolved_area_m2": trimmed.area,
                    "owner_rule": "larger_prepared_component_first",
                }
            )
            polygon = trimmed
        resolved[index] = part.updated(
            footprint=Footprint(
                exterior=tuple(polygon.exterior.coords)[:-1],
                holes=tuple(tuple(r.coords)[:-1] for r in polygon.interiors),
            )
        )
        owned.append(polygon)
    for index, part in enumerate(resolved):
        if part.roof.shape != "flat" and any(
            index != other_index
            and part.footprint.polygon.boundary.intersection(other.footprint.polygon.boundary).length
            > 1e-7
            for other_index, other in enumerate(resolved)
        ):
            resolved[index] = part.updated(roof=RoofSpec(shape="flat", topology="compact"))
            receipt.assumptions.append(
                f"Component {part.identifier}: touching pitched roofs represented by a compact flat roof; roof intersection requires review"
            )
    if changes:
        receipt.identities["component_overlap_resolution"] = changes
        receipt.quality.append(
            f"Bounded component overlap ownership repair removed {sum(x['removed_overlap_m2'] for x in changes):.4f} m2; source outlines retained"
        )
    return tuple(resolved)


def _geometry(record, policy, receipt, overrides):
    from epsm_core import (
        BuildingPart,
        Footprint,
        FootprintCleanupSpec,
        GeometrySpec,
        RoofSpec,
        ZoningSpec,
    )
    from epsm_core.preparation import prepare_geometry
    from epsm_core.roofs import roof_faces
    from shapely.affinity import translate

    if not _geometry_resolved(record) or not record.components:
        raise ValueError("Resolved component geometry is required")
    indexed = {h["component_id"]: h for h in record.heights}
    n = overrides.get("storeys", record.storeys)
    if n is not None and (isinstance(n, bool) or not float(n).is_integer() or n <= 0):
        n = None
    parts = []
    counts = []
    heights = []
    omitted_area = 0.0
    origin = record.geometry.centroid
    receipt.identities["geometry_coordinate_transform"] = {
        "source_crs": "EPSG:3006",
        "model_crs": "local_metres",
        "translation_origin_xy": [origin.x, origin.y],
        "rotation_degrees": 0,
        "inverse": "source_xy = model_xy + translation_origin_xy",
    }
    for i, component in enumerate(record.components):
        component_area = component["geometry"].area
        if (
            len(record.components) > 1
            and component_area < policy.minimum_component_area_m2
            and (omitted_area + component_area) / record.geometry.area
            <= policy.maximum_component_omission_fraction
        ):
            omitted_area += component_area
            receipt.identities.setdefault("omitted_minor_components", []).append(
                {
                    "component_id": component["component_id"],
                    "source_area_m2": component_area,
                    "reason": "below_component_area_and_total_area_fraction_limits",
                }
            )
            receipt.quality.append(
                f"Component {i}: {component_area:.3f} m2 minor footprint omitted from physical model; source component retained"
            )
            continue
        h = indexed.get(component["component_id"])
        matched, resolution = _height_evidence(record, component, h)
        if not matched:
            raise ValueError(f"Missing or geometry-mismatched height: {component['component_id']}")
        if resolution not in (None, "resolved"):
            raise ValueError("Unresolved height evidence")
        if resolution is None:
            receipt.quality.append(
                f"Component {i}: height evidence-resolution metadata unavailable; determined geometry-matched height used"
            )
        measured_form = h.get("roof_form")
        ridge = h.get("ridge_height_m")
        eave = h.get("eave_height_m")
        pitched = (
            measured_form == "pitched_ridge"
            and _positive(eave)
            and (not _positive(ridge) or ridge - eave >= policy.minimum_pitched_rise_m)
        )
        height = h.get("eave_height_m") if pitched else h.get("representative_height_m")
        representative = h.get("representative_height_m")
        reported_count_recovered = (
            pitched
            and n is not None
            and height / n < policy.minimum_full_floor_height_m
            and _positive(representative)
            and policy.minimum_full_floor_height_m
            <= representative / n
            <= policy.maximum_full_floor_height_m
        )
        if pitched and (height < policy.minimum_full_floor_height_m or reported_count_recovered) and _positive(representative):
            pitched = False
            height = representative
            receipt.assumptions.append(
                f"Component {i}: eave conflicts with a plausible reported floor count; representative stored height used with compact roof"
            )
        elif measured_form == "pitched_ridge" and not pitched:
            receipt.assumptions.append(
                f"Component {i}: reported ridge/eave rise below {policy.minimum_pitched_rise_m} m or eave missing; compact roof used"
            )
        if not _positive(height):
            raise ValueError("No usable positive existing body height")
        height = float(height)
        if measured_form != "flat" and not pitched:
            receipt.assumptions.append(
                f"Component {i}: unclear/missing-eave roof completed as compact flat roof at representative height"
            )
        count = n
        if (
            count is None
            or not policy.minimum_full_floor_height_m
            <= height / count
            <= policy.maximum_full_floor_height_m
        ):
            if "storeys" in overrides:
                raise ValueError(
                    "Explicit storey override contradicts the policy floor-height bounds"
                )
            count = max(1, math.floor(height / policy.typical_floor_height_m + 0.5))
            receipt.assumptions.append(
                f"Component {i}: {count} storeys inferred from existing height/type policy; raw reported count retained"
            )
        count = int(count)
        if (
            not policy.minimum_full_floor_height_m
            <= height / count
            <= policy.maximum_full_floor_height_m
        ):
            raise ValueError("No reasonable full-floor geometry under this policy")
        prepared = prepare_geometry(component["geometry"])
        if prepared.status != "accepted":
            raise ValueError(f"Footprint preparation {prepared.status}: {prepared.reasons}")
        polygon = prepared.cleaned_geometry
        if polygon.geom_type != "Polygon":
            raise ValueError("Each component must resolve to a single Polygon")
        # Core roof splitting uses finite construction lines. Use one local frame
        # for every component so those lines intersect the footprint, preserving
        # relative placement and orientation; retain the inverse in the receipt.
        polygon = translate(polygon, xoff=-origin.x, yoff=-origin.y)
        roof = RoofSpec(shape="flat", topology="compact")
        if pitched:
            pitch = policy.default_roof_pitch_deg
            if _positive(ridge) and ridge > height:
                probe = roof_faces(polygon, RoofSpec(shape="gable", pitch_deg=45), height)
                rise = max(v[2] for face in probe for v in face) - height
                pitch = math.degrees(math.atan((ridge - height) / rise))
                receipt.assumptions.append(
                    f"Component {i}: gable shape and dominant-plan ridge direction inferred; pitch fits stored eave/ridge"
                )
            else:
                receipt.assumptions.append(f"Component {i}: assumed gable pitch {pitch} degrees")
            roof = RoofSpec(shape="gable", topology="cold_attic", pitch_deg=pitch)
        labels = (
            component.get("outline_labels")
            or (component.get("attributes") or {}).get("outline_labels")
            or []
        )
        parts.append(
            BuildingPart(
                identifier=f"part_{i}",
                footprint=Footprint(
                    exterior=tuple(polygon.exterior.coords)[:-1],
                    holes=tuple(tuple(r.coords)[:-1] for r in polygon.interiors),
                ),
                storey_elevations_m=tuple(height * j / count for j in range(count + 1)),
                roof=roof,
                height_status="inferred",
                outline_kind="facade" if labels == ["Fasad"] else "roof_edge_proxy",
                outline_reviewed=False,
            )
        )
        counts.append(count)
        heights.append(height)
    parts = _resolve_component_overlaps(parts, policy, receipt)
    basement = overrides.get("basement_storeys", record.basement_storeys)
    if isinstance(basement, bool) or basement not in (None, 0, 1, 2):
        raise ValueError("Only zero, one or two reported basement levels are supported")
    if basement is None:
        basement = 0
        receipt.assumptions.append(
            "Unknown basement completed as no basement in this baseline scenario"
        )
    elif basement == 0:
        receipt.assumptions.append(
            "Zero reported heated basements completed as no physical basement; an unheated basement may exist"
        )
    elif basement == 1:
        receipt.assumptions.append(
            f"Full-footprint conditioned basement; assumed depth {policy.basement_depth_m} m and setpoint {policy.basement_setpoint_c} C"
        )
    else:
        above_ground_area = sum(p.footprint.area_m2 * p.floors for p in parts)
        if not _positive(record.atemp_m2) or record.atemp_m2 > above_ground_area * 1.1:
            raise ValueError(
                "Two reported basement levels require explicit heating evidence when Atemp exceeds above-ground geometry"
            )
        receipt.assumptions.append(
            "Two reported basement levels represented as one aggregated unconditioned below-grade volume; Atemp does not require heated basement area"
        )
        receipt.assumptions.append(
            "Unconditioned basement ceiling uses the archetype ground-floor assembly as an explicit thermal-boundary proxy"
        )
    geometry = GeometrySpec(
        parts=parts,
        footprint_cleanup=FootprintCleanupSpec(enabled=False),
        zoning=ZoningSpec(mode="per_storey"),
        basement_depth_m=policy.basement_depth_m * basement if basement else 0,
        basement_conditioned=basement == 1,
        source_crs="local_metres",
    )
    _field(receipt, "storeys", counts[0] if len(set(counts)) == 1 else counts, "inferred_geometry")
    _field(
        receipt,
        "body_height_m",
        heights[0] if len(heights) == 1 else heights,
        "existing_height_with_assumed_grade",
    )
    _field(receipt, "basement_storeys", basement, "reported_with_geometry_assumptions")
    receipt.assumptions.append(
        "Uniform grade zero and equal floor intervals; terrain exposure, partial heated basements and occupied roof rooms are not reconstructed"
    )
    return geometry


def _ventilation_template(record, policy, receipt, ventilation, era, state, override):
    """Airflow-only system inputs: the catalogue template, or version 3's policy completion."""
    if not policy.catalogue_templates:
        return None
    from epsm_data.templates import ventilation_template_id, ventilation_templates

    reported = override or receipt.fields["ventilation"]["model_state"] == "reported_raw_mapping"
    identifier = ventilation_template_id(record.type.value, era, state, ventilation if reported else None)
    airflow = dict(ventilation_templates()[identifier].values["airflow"])
    receipt.identities["ventilation_template"] = identifier
    _field(
        receipt,
        "ventilation_template",
        identifier,
        "assumed",
        f"Catalogue ventilation template {identifier} for the "
        + ("observed system" if reported else "era default")
        + (f" under {state} renovation" if state not in (None, "existing") else ""),
    )
    return airflow


def _compass_sector(azimuth_deg):
    """Facade sector of an outward normal, clockwise from north: N 315-45, E 45-135, S, W."""
    a = azimuth_deg % 360
    return "N" if a >= 315 or a < 45 else "E" if a < 135 else "S" if a < 225 else "W"


def _facade(record, geometry, glazing, policy, receipt, override):
    from epsm_core import FacadeOverride, FacadeSpec

    if override is not None or not policy.catalogue_templates:
        wwr = override if override is not None else policy.wwr_by_type[record.type.value]
        _field(receipt, "wwr", wwr, "assumed", f"Type-policy WWR {wwr}; not measured glazing")
        return FacadeSpec(default_wwr=wwr, glazing=glazing)
    from epsm_data.templates import facade_assumptions

    table = facade_assumptions(record.type.value)
    by_orientation = table["wwr_by_orientation"]
    overrides = tuple(
        FacadeOverride(facade_id=facade.facade_id, wwr=by_orientation[_compass_sector(facade.azimuth_deg)])
        for facade in geometry.facades()
        if by_orientation[_compass_sector(facade.azimuth_deg)] != table["default_wwr"]
    )
    _field(
        receipt,
        "wwr",
        table["default_wwr"],
        "assumed",
        f"Catalogue facade WWR ({table['tier']}): default {table['default_wwr']}, "
        + "N/E/S/W " + "/".join(str(by_orientation[k]) for k in "NESW")
        + "; not measured glazing",
    )
    return FacadeSpec(default_wwr=table["default_wwr"], glazing=glazing, overrides=overrides)


def _operation(
    name,
    year,
    *,
    airflow_template=None,
    ventilation=None,
    infiltration,
    geometry,
    area,
    policy,
    receipt,
    residential_type="single_family",
):
    from epsm_core import ScheduleSpec, resolve_operating_profile
    from epsm_data import (
        load_operating_profile,
        select_dhw_profile,
        select_operating_profile,
    )

    from ._programme_airflow import normal_use_airflow

    if name == "residential":
        profile = select_operating_profile(residential_type)
        resolved = resolve_operating_profile(profile, calendar={"calendar_year": year})
        use = resolved.operation
        dhw = select_dhw_profile(residential_type, purpose="epc_normal_use")
        use = resolve_operating_profile(dhw, previous=use).operation
        receipt.assumptions.append(
            f"Residential DHW uses {dhw.profile_id}; standardized normal use, not measured consumption"
        )
        flow = resolved.assumptions["airflow"]["mechanical_vent_l_s_m2"]
        fraction = ScheduleSpec.constant(1)
    elif name in {"office", "school"}:
        profile = select_operating_profile(name)
        dates = _active_dates(year, profile.values["reference_active_days"], school=name == "school")
        resolved = resolve_operating_profile(profile, calendar={
            "calendar_year": year, "active_dates": dates,
            "calendar_source": "ubem_v1: assumed evenly distributed weekdays; school summer closure",
        }, **({"zone_role": "classrooms"} if name == "school" else {}))
        use = resolved.operation
        inputs = resolved.assumptions
        flow = inputs["airflow"]["mechanical_vent_l_s_m2"]
        fraction = ScheduleSpec.model_validate(inputs["airflow"]["mechanical_vent_fraction"])
        receipt.assumptions.append(
            f"{name}: versioned Sveby equivalent programme with assumed calendar"
        )
    else:
        profile = load_operating_profile("generic_other")
        resolved = resolve_operating_profile(profile)
        use = resolved.operation
        flow = resolved.assumptions["airflow"]["mechanical_vent_l_s_m2"]
        fraction = ScheduleSpec.model_validate(resolved.assumptions["airflow"]["mechanical_vent_fraction"])
        receipt.assumptions.append(
            f"{name}: {profile.profile_id} screening fallback; actual use and schedule unresolved"
        )
        receipt.quality.append(
            f"{name} operational programme uses a generic fallback; review before interpreting demand error"
        )
    # The template sets the system and its heat recovery; the operating profile keeps
    # the occupied flow rates and natural ventilation keeps the normal-use timetable.
    # A bare ``ventilation`` system keeps version 3's policy completion.
    if airflow_template is None:
        airflow_template = {
            "topology": ventilation,
            "sensible_recovery_effectiveness": policy.ftx_recovery if ventilation == "FTX" else 0,
        }
    topology = airflow_template["topology"]
    air = normal_use_airflow(
        ventilation=topology, infiltration=infiltration, flow_l_s_m2=flow,
        fraction=fraction, reference_area_m2=area,
        conditioned_volume_m3=geometry.conditioned_volume_m3,
        recovery_effectiveness=airflow_template.get("sensible_recovery_effectiveness", 0),
    )
    if topology == "S":
        receipt.assumptions.append(
            "Natural ventilation uses the source normal-use outdoor-air timetable "
            "as an equivalent-flow assumption, not a pressure-driven airflow model"
        )
    source = profile.profile_id + (" + " + dhw.profile_id if name == "residential" else "")
    return use, air, source


_CARRIER_FIELDS = {
    "district_heat": ["EgiFjarrvarme", "EgiFjarrvarmeUPPV"],
    "electric_direct": [
        "EgiElVatten",
        "EgiElDirekt",
        "EgiElLuft",
        "EgiElVattenUPPV",
        "EgiElDirektUPPV",
        "EgiElLuftUPPV",
    ],
    "heat_pump": [
        "EgiPumpMark",
        "EgiPumpFranluft",
        "EgiPumpLuftLuft",
        "EgiPumpLuftVatten",
        "EgiPumpMarkUPPV",
        "EgiPumpFranluftUPPV",
        "EgiPumpLuftLuftUPPV",
        "EgiPumpLuftVattenUPPV",
    ],
    "fuel": [
        "EgiOlja",
        "EgiGas",
        "EgiVed",
        "EgiFlis",
        "EgiOvrBiobransle",
        "EgiOljaUPPV",
        "EgiGasUPPV",
        "EgiVedUPPV",
        "EgiFlisUPPV",
        "EgiOvrBiobransleUPPV",
    ],
}


def _heating_carriers(record):
    """Carrier families with positive reported energy on a single-building EPC."""
    return [
        name
        for name, sources in _CARRIER_FIELDS.items()
        if record.single_building_epc and any(_positive(record.observation(s)[0]) for s in sources)
    ]


def _delivery(record, policy, receipt):
    from epsm_core import DeliverySpec, HeatingDeliverySpec, ScheduleSpec

    present = _heating_carriers(record)
    if len(present) != 1:
        receipt.quality.append(
            "Heating carrier mixed/unavailable: model reports ideal thermal demand; no purchased-energy conversion"
        )
        return DeliverySpec()
    carrier = present[0]
    options = {
        "carrier": carrier,
        "source": "ubem_v1: carrier indicated by raw EPC energy fields; effective efficiency/COP assumption",
    }
    if carrier == "heat_pump":
        options["heat_pump_cop"] = ScheduleSpec.constant(policy.heat_pump_cop)
    if carrier == "fuel":
        options["efficiency"] = policy.fuel_efficiency
    receipt.assumptions.append(
        f"Heating carrier {carrier}; effective delivery parameters from policy, not calibrated performance"
    )
    return DeliverySpec(heating=HeatingDeliverySpec(**options))


@dataclass(frozen=True)
class EPSMBuilding:
    spec: object
    type: BuildingType
    receipt: Receipt

    @classmethod
    def from_record(
        cls,
        record: BuildingRecord,
        *,
        weather,
        policy="ubem_v1",
        overrides=None,
        preflight=True,
        energyplus=None,
    ):
        receipt = deepcopy(record.receipt)
        try:
            if isinstance(policy, str):
                if policy != "ubem_v1":
                    raise ValueError("Unknown model policy")
                policy = ModelPolicy()
            if not isinstance(policy, ModelPolicy):
                raise TypeError("policy must be a ModelPolicy or 'ubem_v1'")
            if not isinstance(record, BuildingRecord):
                raise TypeError("Supply a BuildingRecord")
            if record.type.value not in {"single_family", "multi_family", "school", "office"}:
                raise ValueError("No v1 physical archetype for this building type")
            if not _verified_existing(record):
                raise ValueError("v1 model assembly requires verified existing-building status")
            if any(
                r.get("temporal_status") in {"construction_after_certificate", "temporal_conflict"}
                for r in record.epc_results
            ):
                raise ValueError("EPC temporal conflict requires review")
            from epsm_core import (
                BuildingSpec,
                FoundationSpec,
                ProgramBlend,
                ProgramComponent,
                ScheduleSpec,
                UnconditionedExchangeSpec,
                ZoneUseSpec,
            )
            from epsm_core.compiler import EnergyPlusCompiler
            from epsm_core.specs.provenance import ProvenanceSpec, SourceRecord

            from .catalogue_application import resolve_building_archetype

            overrides = dict(overrides or {})
            if set(overrides) - {
                "storeys",
                "basement_storeys",
                "construction_year",
                "ventilation",
                "wwr",
                "climate_zone",
                "renovation_state",
                "component_states",
                "component_sources",
            }:
                raise ValueError("Unknown model override")
            renovation_state = overrides.get("renovation_state")
            if renovation_state not in (None, "existing", "standard", "advanced"):
                raise ValueError("renovation_state must be existing, standard or advanced")
            receipt.identities["policy"] = asdict(policy)
            receipt.identities["overrides"] = overrides
            geometry = _geometry(record, policy, receipt, overrides)
            year = overrides.get("construction_year", record.facts.get("construction_year"))
            if not year:
                year = (
                    record.observation("EgenNybyggAr", integer=True)[0]
                    if record.single_building_epc
                    else None
                )
            if not year:
                raise ValueError("Construction year missing; supply an explicit override")
            if (
                isinstance(year, bool)
                or not math.isfinite(float(year))
                or not float(year).is_integer()
            ):
                raise ValueError("Construction year must be an integer")
            if record.facts.get("construction_year") and record.single_building_epc:
                epc_year = record.observation("EgenNybyggAr", integer=True)[0]
                if epc_year and epc_year != record.facts["construction_year"]:
                    receipt.quality.append("Construction years disagree; register year selected")
            _field(
                receipt,
                "construction_year",
                int(year),
                "assumed" if "construction_year" in overrides else "reported",
            )
            # SE.07 has one catalogue configuration; older eras default to existing.
            from epsm_data.classification import era_for_year

            if era_for_year(int(year)) == "SE.07":
                if renovation_state is not None:
                    raise ValueError("SE.07 has one catalogue configuration; omit renovation_state")
            elif renovation_state is None:
                renovation_state = "existing"
            area = record.atemp_m2
            if not _positive(area):
                area = geometry.conditioned_floor_area_m2
                _field(
                    receipt,
                    "atemp_m2",
                    area,
                    "assumed_geometric_load_area",
                    "Atemp unavailable/invalid/scope-unresolved; geometric conditioned area is the operational reference, not a new reported Atemp",
                )
            else:
                _field(receipt, "atemp_m2", area, "reported_raw_mapping")
            ventilation = _ventilation(record, policy, receipt, overrides.get("ventilation"))
            zone = overrides.get("climate_zone", policy.catalogue_climate_zone)
            receipt.assumptions.append(
                f"Catalogue climate classification {zone}; default is an explicit classification assumption, not geographic inference"
            )
            fabric = resolve_building_archetype(
                category=record.type.value,
                construction_year=int(year),
                climate_zone=zone,
                ventilation=ventilation,
                default_state=renovation_state,
                component_states=overrides.get("component_states"),
                component_sources=overrides.get("component_sources"),
                tabula_reference_area_m2=area,
                conditioned_volume_m3=geometry.conditioned_volume_m3,
            )
            airflow_template = _ventilation_template(
                record,
                policy,
                receipt,
                ventilation,
                fabric["assignment"]["era"],
                renovation_state,
                overrides.get("ventilation"),
            )
            if fabric["infiltration_reference_basis"] == "core_conditioned_volume":
                receipt.assumptions.append(
                    "TABULA reference area assumed equal operational load reference; infiltration converted to physical volume"
                )
            if callable(weather):
                weather = weather(record)
            elif isinstance(weather, dict):
                weather = weather[record.building_id]
            if not isinstance(weather, WeatherReference):
                weather = WeatherReference.from_epw(weather, calendar_year=policy.calendar_year)
            climate = weather.climate()
            receipt.identities["weather"] = asdict(weather)
            primary = (
                "residential"
                if record.type.value.startswith(("single", "multi"))
                else record.type.value
            )
            shares = record.programmes
            if not shares:
                shares = {primary: 1.0}
                receipt.assumptions.append(
                    f"Programme distribution unavailable; 100% {primary} operational scenario"
                )
            shares = _effective_programme_shares(
                shares,
                primary=primary,
                minimum_share=policy.minimum_programme_blend_share,
                receipt=receipt,
            )
            programmes = {
                name: _operation(
                    name,
                    climate.calendar_year,
                    airflow_template=airflow_template,
                    ventilation=ventilation,
                    infiltration=fabric["core_airflow_inputs"],
                    geometry=geometry,
                    area=area,
                    policy=policy,
                    receipt=receipt,
                    residential_type="single_family"
                    if record.type == BuildingType.RESIDENTIAL_SINGLE_FAMILY
                    else "multi_family",
                )
                for name in shares
            }
            control_use, _, _ = _operation(
                primary,
                climate.calendar_year,
                airflow_template=airflow_template,
                ventilation=ventilation,
                infiltration=fabric["core_airflow_inputs"],
                geometry=geometry,
                area=area,
                policy=policy,
                receipt=receipt,
                residential_type="single_family"
                if record.type == BuildingType.RESIDENTIAL_SINGLE_FAMILY
                else "multi_family",
            )
            blend = ProgramBlend(
                source="ubem_v1: EPC heated-area shares after documented sub-threshold allocation; effective zones with primary-use controls and common building ventilation",
                components=tuple(
                    ProgramComponent(
                        name=name,
                        area_fraction=share,
                        use=programmes[name][0],
                        airflow=programmes[name][1],
                        source=programmes[name][2],
                    )
                    for name, share in shares.items()
                ),
            )
            use, airflow = blend.resolve(
                calendar_year=climate.calendar_year, control_use=control_use
            )
            receipt.identities["programme_blend"] = blend.model_dump(mode="json")
            receipt.identities["archetype_assignment"] = fabric["assignment"]
            from epsm_data import archetype_to_dict

            receipt.identities["archetype_definition"] = archetype_to_dict(fabric["archetype"])
            receipt.assumptions.append(
                "Matrix existing state is a construction-era representative; renovations are not inferred"
                if renovation_state == "existing" else
                "SE.07 single configuration is the current-code representative; renovations are not inferred"
                if renovation_state is None else
                f"Matrix {renovation_state} renovation package is an explicit scenario, not an observed building state"
            )
            receipt.assumptions.append(
                "Operational reference area distributed by conditioned geometric area; it does not change heated extent"
            )
            assignments = ()
            if geometry.basement_conditioned:
                assignments = (
                    ZoneUseSpec(
                        zone_kind="basement",
                        source="ubem_v1 assumed basement controls",
                        use=use.updated(
                            heating_setpoint=ScheduleSpec.constant(policy.basement_setpoint_c)
                        ),
                    ),
                )
            attic = any(geometry.roof_for(p).topology == "cold_attic" for p in geometry.parts)
            exchanges = (
                (
                    UnconditionedExchangeSpec(
                        zone_kind="attic",
                        outdoor_air_ach=policy.attic_outdoor_air_ach,
                        source="ubem_v1 explicit assumed attic exchange",
                    ),
                )
                if attic
                else ()
            )
            if attic:
                receipt.assumptions.append(
                    f"Assumed attic outdoor exchange {policy.attic_outdoor_air_ach} ACH"
                )
            facade = _facade(record, geometry, fabric["glazing"], policy, receipt, overrides.get("wwr"))
            receipt.identities["physical_conditioned_floor_area_m2"] = (
                geometry.conditioned_floor_area_m2
            )
            receipt.identities["load_to_physical_area_ratio"] = (
                area / geometry.conditioned_floor_area_m2
            )
            _field(
                receipt,
                "physical_conditioned_area_m2",
                geometry.conditioned_floor_area_m2,
                "derived_model_geometry",
            )
            receipt.assumptions.append(
                "Baseline has no shading neighbours or reviewed party-wall assignments; these can be supplied through native Core inputs"
            )
            if not 0.75 <= area / geometry.conditioned_floor_area_m2 <= 1.25:
                receipt.quality.append(
                    "Atemp/geometric conditioned area outside provisional 0.75–1.25 screen; review heated extent"
                )
            sources = [
                SourceRecord(
                    field_path="geometry",
                    status="inferred",
                    source=f"{record.dataset_id}/{record.building_id}; existing component geometry/heights; {policy.name}/{policy.version}",
                ),
                SourceRecord(
                    field_path="load_reference_area_m2",
                    status="inferred",
                    source="Scope-qualified EPC Atemp or declared geometric fallback",
                ),
                SourceRecord(
                    field_path="envelope", status="assumed", source=str(fabric["assignment"])
                ),
                SourceRecord(
                    field_path="use",
                    status="assumed",
                    source="Versioned operational profiles or labelled generic fallback with declared effective programme controls",
                ),
                SourceRecord(
                    field_path="airflow",
                    status="assumed",
                    source="Matrix infiltration handoff and declared ventilation completion",
                ),
                SourceRecord(
                    field_path="facade.default_wwr",
                    status="assumed",
                    source=f"epsm_data facade_assumptions; {policy.name}/{policy.version}"
                    if policy.catalogue_templates and "wwr" not in overrides
                    else f"{policy.name}/{policy.version}",
                ),
            ]
            spec = BuildingSpec(
                identifier=record.building_id,
                geometry=geometry,
                load_reference_area_m2=area,
                facade=facade,
                envelope=fabric["envelope"].updated(
                    foundation=FoundationSpec(),
                    ground_temperature=None,
                    basement_ceiling=(
                        fabric["envelope"].basement_ceiling or fabric["envelope"].ground
                        if geometry.basement_depth_m and not geometry.basement_conditioned
                        else fabric["envelope"].basement_ceiling
                    ),
                ),
                climate=climate,
                use=use,
                airflow=airflow,
                zone_uses=assignments,
                unconditioned_exchange=exchanges,
                delivery=_delivery(record, policy, receipt),
                provenance=ProvenanceSpec(records=tuple(sources)),
            )
            receipt.identities["physical_hash"] = spec.physical_hash()
            for package in ["epsm_core", "epsm_data"]:
                try:
                    version = importlib.metadata.version(package)
                except importlib.metadata.PackageNotFoundError:
                    version = getattr(
                        importlib.import_module(package), "__version__", "source-checkout"
                    )
                receipt.identities[package] = version
            receipt.identities["implementation_sha256"] = {
                name: implementation_hash(name)
                for name in ("epsm", "epsm_db", "epsm_core", "epsm_data")
            }
            if preflight:
                _, compiled = EnergyPlusCompiler(energyplus).compile(spec)
                receipt.identities["compilation"] = {
                    "run_id": compiled.run_id,
                    "spec_sha256": compiled.spec_sha256,
                }
                receipt.ready_for_simulation = True
            else:
                receipt.quality.append(
                    "Native spec validated; EnergyPlus compilation preflight not requested"
                )
            receipt.assumptions = list(dict.fromkeys(receipt.assumptions))
            receipt.quality = list(dict.fromkeys(receipt.quality))
            return cls(spec, record.type, receipt), receipt
        except (
            ValueError,
            TypeError,
            ImportError,
            KeyError,
            FileNotFoundError,
            RuntimeError,
        ) as exc:
            receipt.errors.append(f"{type(exc).__name__}: {exc}")
            receipt.ready_for_simulation = False
            raise ModelAssemblyError(str(exc), receipt) from exc

    @classmethod
    def from_records(cls, records, **kwargs):
        buildings, receipts = [], []
        selection = getattr(records, "receipt", None)
        for record in records:
            try:
                building, receipt = cls.from_record(record, **kwargs)
                buildings.append(building)
            except ModelAssemblyError as exc:
                receipt = exc.receipt
            if selection and selection.truncated:
                receipt.quality.append(
                    f"Input selection truncated; retrieve remaining records after_uuid={selection.next_cursor}"
                )
            receipts.append(receipt)
        return tuple(buildings), tuple(receipts)

    def simulate(self, directory, *, energyplus=None, **kwargs):
        from epsm_core import EnergyPlusRunner

        return EnergyPlusRunner(energyplus).run(self.spec, directory, **kwargs)

    def write(self, path):
        """Write model and receipt beside it; refuse to overwrite either file."""
        import json

        path = Path(path)
        receipt_path = path.with_suffix(path.suffix + ".receipt.json")
        if path.exists() or receipt_path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.spec.model_dump_json(indent=2))
        receipt_path.write_text(
            json.dumps(self.receipt.to_dict(), indent=2, ensure_ascii=False, default=json_default)
        )
        return path, receipt_path
