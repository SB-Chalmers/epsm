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
from epsm_db.epc_systems import observed_systems_from_record
from epsm_db.records import (
    BuildingRecord,
    Receipt,
    implementation_hash,
    json_default,
)
from epsm_db.weather import WeatherReference

from ._solar_shading import solar_shading_factor, validate_solar_shading


@dataclass(frozen=True)
class ModelPolicy:
    name: str = "ubem_v1"
    version: str = "13"
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
    fuel_efficiency: float = 0.9
    calendar_year: int = 2023
    catalogue_climate_zone: str = "SE.Zone3"
    # Version 4: catalogue ventilation templates and facade window ratios. False
    # restores version 3's type defaults below (one WWR and one FTX recovery).
    catalogue_templates: bool = True
    # Version 5: heat-pump COP from Data's delivery template. Version 7: the COP
    # follows the EPC heat-pump type where Data supports it. "measured" selects
    # Data's observed stock operation for existing buildings; "sveby" is normal use.
    operating_standard: str = "sveby"
    # Version 6: Sveby window solar shading. "behaviour" (default) is the occupant
    # factor (0.71 single-family and office, 0.65 school), as fixed obstructions belong
    # in geometry; "total" is Sveby's combined factor (0.50; school 0.65); None turns it
    # off (1.0, versions 1-5); a number in (0, 1] is used as given. Multi-family is not
    # applied (named choices give 1.0; see epsm._solar_shading.NOT_APPLIED).
    solar_shading: str | float | None = "behaviour"
    # Version 8: single-family storey check. LiDAR heights of houses built after
    # their area was scanned can be tree canopy (unclassified points include
    # vegetation), which height/typical-floor turns into 3-8 storeys. When the
    # storey count comes from height, it is checked against the EPC Atemp, or the
    # register living area, and replaced by the area-implied count if implausible.
    # False restores version 7's height-only storey inference.
    single_family_storey_check: bool = True
    single_family_maximum_storeys: int = 3
    single_family_minimum_area_ratio: float = 0.6
    single_family_net_to_gross_area: float = 0.88
    # Version 9: single-family slab edge and household electricity.
    # Swedish slab-on-grade has an insulated edge beam (kantelement): EPS-bygg
    # Grundboken p. 69, table 1 gives typical edge-beam psi 0.25-0.06 W/mK for
    # 50-150 mm front insulation. Kiva otherwise leaves the slab edge bare. An
    # insulated slab gets this much vertical edge insulation of the same material,
    # down to the given depth below the slab. 0 restores version 8.
    single_family_slab_edge_insulation_m: float = 0.10
    single_family_slab_edge_depth_m: float = 0.3
    # BEN (BFS 2016:12, table 2:1) normal use for småhus: household electricity
    # 30 kWh/m2 Atemp, 70 % usable as heat in the heating season. The Sveby
    # residential profile is multi-family (21 kWh/m2). None restores version 8.
    single_family_household_electricity_kwh_m2: float | None = 30.0
    household_electricity_heat_fraction: float = 0.70
    # Version 10: EPC ventilation with FTX among several ticked systems (for
    # example F+FTX or FT+FTX) is modelled as FTX at the observed-FTX template.
    # The EPC has no per-system shares, and a building with an FTX unit has heat
    # recovery on at least part of its air; STIL2 (2005) and STIL3 (ER 2025:25)
    # found no exhaust-only or natural-draught offices. Before version 10 such a
    # certificate was "conflicting" and the catalogue's era default ran (S, F or
    # FT without recovery in SE.01-SE.03). False restores version 9.
    ventilation_conflict_ftx: bool = True
    # Version 11: shading-only neighbours (lake components within this radius, at
    # their representative height) for database-backed records or caller-supplied
    # rows. None turns context off (versions 1-10). (Version 10's ventilation rule
    # shipped without a version bump; 11 marks both.)
    context_radius_m: float | None = 100.0
    context_min_height_m: float = 2.0
    # Version 12: single-family SE.06 later-build envelope. SE.06 spans 2006-2021,
    # but Swedish energy rules tightened inside it: from 1 Feb 2009 (BBR 16, BFS
    # 2008:20) electrically heated new buildings, which includes heat-pump småhus,
    # had a separate, lower limit (95/75/55 kWh/m2 in zones I-III against
    # 150/130/110), and from 2012 (BBR 19, BFS 2011:6) the other limit fell to
    # 130/110/90 with Um 0.50 -> 0.40 W/m2K (Boverket konsekvensutredningar
    # BFS 2011:6 and BFS 2015:3). Houses built under those rules get the SE.06
    # advanced constructions, windows and airtightness (the SE.07 values) in their
    # existing state; ventilation stays as observed. The size of the envelope
    # change is the catalogue's authored values, not a measured as-built survey.
    # Tested on fresh houses (epsm_studies sf-fix-2026-11-25). False restores
    # version 11.
    single_family_se06_later_build: bool = True
    single_family_later_build_electric_year: int = 2009
    single_family_later_build_any_year: int = 2012
    # Version 13: school SE.06 earlier-build envelope. School SE.06 spans
    # 2006-2021; BBR 19 (BFS 2011:6), in force from 2012, lowered the limit for
    # non-electric lokaler from 100 to 80 kWh/m2 in zone III and Um from 0.70 to
    # 0.60 W/m2K (Boverket konsekvensutredning BFS 2011:6). Schools built before
    # 2012 get the school SE.05 existing wall, roof and window in their existing
    # state; the era, ventilation, airtightness and operation stay SE.06. The size
    # of the change is the catalogue's SE.05 values, not a measured survey.
    # Tested on school SE.06 (epsm_studies cohort-dives-2026-11-25). False
    # restores version 12.
    school_se06_earlier_build: bool = True
    school_earlier_build_before_year: int = 2012
    school_earlier_build_donor_year: int = 2005
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
        if self.context_radius_m is not None and (
            isinstance(self.context_radius_m, bool)
            or not math.isfinite(float(self.context_radius_m))
            or self.context_radius_m <= 0
        ):
            raise ValueError("Context radius must be positive or None")
        if not math.isfinite(self.context_min_height_m) or self.context_min_height_m < 0:
            raise ValueError("Context minimum height must be finite and non-negative")
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
        ]
        if any(not math.isfinite(x) or x <= 0 for x in positive):
            raise ValueError("Height and depth assumptions must be finite and positive")
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
        if self.operating_standard not in {"sveby", "measured"}:
            raise ValueError("operating_standard must be sveby or measured")
        validate_solar_shading(self.solar_shading)
        if (
            isinstance(self.single_family_maximum_storeys, bool)
            or not isinstance(self.single_family_maximum_storeys, int)
            or self.single_family_maximum_storeys < 1
        ):
            raise ValueError("Single-family maximum storeys must be a positive integer")
        if not 0 < self.single_family_minimum_area_ratio < 1:
            raise ValueError("Single-family minimum area ratio must be between 0 and 1")
        if not 0 < self.single_family_net_to_gross_area <= 1:
            raise ValueError("Single-family net-to-gross area must be in (0,1]")
        if not math.isfinite(self.single_family_slab_edge_insulation_m) or self.single_family_slab_edge_insulation_m < 0:
            raise ValueError("Slab edge insulation must be finite and nonnegative")
        if not math.isfinite(self.single_family_slab_edge_depth_m) or self.single_family_slab_edge_depth_m < 0:
            raise ValueError("Slab edge depth must be finite and nonnegative")
        if self.single_family_household_electricity_kwh_m2 is not None and not (
            math.isfinite(self.single_family_household_electricity_kwh_m2)
            and self.single_family_household_electricity_kwh_m2 >= 0
        ):
            raise ValueError("Household electricity must be finite and nonnegative")
        if not 0 <= self.household_electricity_heat_fraction <= 1:
            raise ValueError("Household electricity heat fraction must be in [0,1]")


class ModelAssemblyError(ValueError):
    def __init__(self, message, receipt):
        self.receipt = receipt
        super().__init__(message)


def _positive(value):
    return value is not None and math.isfinite(float(value)) and float(value) > 0


def _register_living_area(record):
    """Lantmäteriet register total living area (totalBoarea) in m2, or None."""
    sources = [((record.facts.get("attributes") or {}).get("original_values") or {})]
    sources += [(p or {}).get("original_values") or {} for p in record.facts.get("purposes") or ()]
    for values in sources:
        for key in ("Byggnad/Bostad/totalBoarea", "Bostad/totalBoarea"):
            raw = values.get(key)
            if isinstance(raw, list):
                raw = raw[0] if raw else None
            try:
                area = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(area) and area > 0:
                return area
    return None


def _storey_area_anchor(record, overrides):
    """Floor area that bounds a single-family storey count: EPC Atemp, else register living area."""
    atemp = record.atemp_m2
    if _positive(atemp):
        return float(atemp), "EPC Atemp"
    living = _register_living_area(record)
    if living is not None:
        return living, "register living area (totalBoarea)"
    return None, None


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


def _observed_systems(record):
    """What the selected EPC reports, when it describes this building alone."""
    return observed_systems_from_record(record) if record.single_building_epc else None


def _ventilation(record, policy, receipt, override):
    if override:
        if override not in {"S", "F", "FT", "FTX"}:
            raise ValueError("Ventilation must be S, F, FT or FTX")
        _field(receipt, "ventilation", override, "assumed", "Caller-supplied ventilation topology")
        return override
    observed = _observed_systems(record)
    result = observed.ventilation if observed else None
    if (
        result is None
        and policy.ventilation_conflict_ftx
        and observed is not None
        and observed.ventilation_status == "conflicting"
        and "FTX" in observed.reported_ventilation
    ):
        result = "FTX"
        receipt.assumptions.append(
            "EPC ventilation " + "+".join(observed.reported_ventilation)
            + " modelled as FTX: an FTX unit is present and the EPC gives no per-system shares (version 10)"
        )
    if result:
        if result == "Fmed":
            # Exhaust with heat recovery, in practice an exhaust-air heat pump. With heat-pump
            # heating the exhaust air is the pump's source and its COP carries the recovery,
            # so the building is modelled as F. Otherwise the pump's electricity is not in the
            # heating carrier and the recovered heat lowers it: modelled as recovery on the
            # exhaust flow, FTX at the catalogue's observed-FTX effectiveness.
            result = "F" if observed.heating_carrier == "heat_pump" else "FTX"
            receipt.assumptions.append(
                f"EPC ventilation F with heat recovery modelled as {result}: "
                + ("recovery carried by the heat pump's COP" if result == "F" else "no heat-pump heating carrier")
            )
        _field(receipt, "ventilation", result, "reported_raw_mapping")
    else:
        result = policy.ventilation_by_type[record.type.value]
        status = observed.ventilation_status if observed else "unavailable"
        _field(
            receipt,
            "ventilation",
            result,
            "assumed",
            f"Ventilation {status}; type default {result}"
            + ("; with catalogue templates the era's default template sets the airflow"
               if policy.catalogue_templates else ""),
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
    anchor_area, anchor_source = (None, None)
    if policy.single_family_storey_check and record.type.value == "single_family":
        anchor_area, anchor_source = _storey_area_anchor(record, overrides)
        if anchor_area is not None:
            reported_basement = overrides.get("basement_storeys", record.basement_storeys)
            if reported_basement == 1 and anchor_source == "EPC Atemp":
                # A conditioned basement is part of Atemp but not of the above-ground storeys.
                anchor_area -= policy.single_family_net_to_gross_area * record.geometry.area
            if anchor_area <= 0:
                anchor_area = None
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
            if anchor_area is not None:
                footprint = record.geometry.area
                if (
                    count > policy.single_family_maximum_storeys
                    or anchor_area / (footprint * count) < policy.single_family_minimum_area_ratio
                ):
                    implied = min(
                        policy.single_family_maximum_storeys,
                        max(1, round(anchor_area / (policy.single_family_net_to_gross_area * footprint))),
                    )
                    receipt.assumptions.append(
                        f"Component {i}: {count} storeys from {height:.2f} m height are implausible for a single-family house "
                        f"with {anchor_source} {anchor_area:.0f} m2 on a {footprint:.0f} m2 footprint (likely vegetation in the LiDAR); "
                        f"{implied} storeys at {policy.typical_floor_height_m} m used with a compact roof"
                    )
                    receipt.quality.append(
                        f"Component {i}: single-family height {height:.2f} m replaced by {anchor_source}-implied storeys"
                    )
                    count = implied
                    height = implied * policy.typical_floor_height_m
                    pitched = False
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


def _foundation(record, envelope, geometry, policy, receipt):
    """Kiva foundation; single-family insulated slabs get an insulated edge beam (version 7)."""
    from epsm_core import FoundationSpec
    from epsm_core.specs.physics import ConstructionSpec

    if (
        record.type.value != "single_family"
        or policy.single_family_slab_edge_insulation_m <= 0
        or geometry.basement_depth_m
    ):
        return FoundationSpec()
    layers = envelope.ground.layers
    insulation = [
        layer for layer in layers
        if layer.material.conductivity_w_mk <= 0.06 and layer.thickness_m >= 0.05
    ]
    if not insulation:
        receipt.assumptions.append(
            "Slab without an insulation layer of at least 50 mm: no insulated edge beam assumed"
        )
        return FoundationSpec()
    insulation = min(insulation, key=lambda layer: layer.material.conductivity_w_mk)
    structure = max(layers, key=lambda layer: layer.material.conductivity_w_mk)
    thickness = min(policy.single_family_slab_edge_insulation_m, insulation.thickness_m)
    edge = ConstructionSpec(layers=(insulation.model_copy(update={"thickness_m": thickness}), structure))
    receipt.assumptions.append(
        f"Insulated slab edge beam: {thickness * 1000:.0f} mm of the slab insulation outside the slab's "
        f"structural layer, {policy.single_family_slab_edge_depth_m} m below the slab "
        "(Swedish kantelement practice, EPS-bygg Grundboken p. 69)"
    )
    return FoundationSpec(
        footing_wall=edge,
        wall_depth_below_slab_m=policy.single_family_slab_edge_depth_m,
        source="ubem_v1 v9: Kiva defaults with an assumed insulated slab edge beam (EPS-bygg Grundboken p. 69)",
    )


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


def _shading(record, policy, receipt):
    """Window solar factor from the building type's Sveby profile and the policy choice."""
    from epsm_data import select_operating_profile

    values = select_operating_profile(record.type.value).values
    factor, text = solar_shading_factor(values, policy.solar_shading, record.type.value)
    if factor is None:
        factor, text = 1.0, f"No Sveby solar shading data for {record.type.value}; factor 1.0"
    _field(receipt, "solar_shading_factor", factor, "assumed", text)
    return factor


def _facade(record, geometry, glazing, policy, receipt, override):
    from epsm_core import FacadeOverride, FacadeSpec

    shading = _shading(record, policy, receipt)
    if override is not None or not policy.catalogue_templates:
        wwr = override if override is not None else policy.wwr_by_type[record.type.value]
        _field(receipt, "wwr", wwr, "assumed", f"Type-policy WWR {wwr}; not measured glazing")
        return FacadeSpec(default_wwr=wwr, glazing=glazing, solar_shading_factor=shading)
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
    return FacadeSpec(
        default_wwr=table["default_wwr"],
        glazing=glazing,
        overrides=overrides,
        solar_shading_factor=shading,
    )


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
    era=None,
    residential_type="single_family",
):
    from epsm_core import (
        ScheduleSpec,
        natural_exchange_for_total,
        resolve_operating_profile,
    )
    from epsm_data import (
        load_operating_profile,
        select_dhw_profile,
        select_operating_profile,
    )

    from ._programme_airflow import measured_air_change, normal_use_airflow

    def selected(use):
        if policy.operating_standard == "sveby":
            return select_operating_profile(use)
        profile = select_operating_profile(use, standard="measured", era=era)
        receipt.assumptions.append(profile.notes[-1])
        return profile

    if name == "residential":
        profile = selected(residential_type)
        resolved = resolve_operating_profile(profile, calendar={"calendar_year": year})
        use = resolved.operation
        dhw = select_dhw_profile(residential_type, purpose="epc_normal_use")
        use = resolve_operating_profile(dhw, previous=use).operation
        receipt.assumptions.append(
            f"Residential DHW uses {dhw.profile_id}; standardized normal use, not measured consumption"
        )
        if (
            residential_type == "single_family"
            and policy.single_family_household_electricity_kwh_m2 is not None
            and use.equipment_gain_w_m2 > 0
        ):
            schedule = use.equipment_fraction
            hours = (
                sum(schedule.annual_values)
                if schedule.annual_values is not None
                else sum(schedule.values) / len(schedule.values) * 8760
            )
            current = use.equipment_gain_w_m2 * hours / 1000
            target = (
                policy.single_family_household_electricity_kwh_m2
                * policy.household_electricity_heat_fraction
            )
            use = use.updated(equipment_gain_w_m2=use.equipment_gain_w_m2 * target / current)
            receipt.assumptions.append(
                f"Single-family household electricity {policy.single_family_household_electricity_kwh_m2:g} kWh/m2 "
                f"with {policy.household_electricity_heat_fraction:.0%} usable as heat (BEN BFS 2016:12 table 2:1, småhus): "
                f"internal gain {current:.1f} -> {target:.1f} kWh/m2 per year"
            )
        flow = resolved.assumptions["airflow"]["mechanical_vent_l_s_m2"]
        fraction = ScheduleSpec.constant(1)
    elif name in {"office", "school"}:
        profile = selected(name)
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
    total = measured_air_change(profile, topology)
    if total is not None:
        # Per programme, so a mixed-use building keeps the other uses' exchange.
        air = air.updated(natural_exchange_ach=natural_exchange_for_total(
            total, air, volume_m3=geometry.conditioned_volume_m3, reference_area_m2=area,
        ))
        receipt.assumptions.append(
            f"Natural exchange from a measured total air change of {total} ACH, net of infiltration"
        )
    if topology == "S":
        receipt.assumptions.append(
            "Natural ventilation uses the source normal-use outdoor-air timetable "
            "as an equivalent-flow assumption, not a pressure-driven airflow model"
        )
    source = profile.profile_id + (" + " + dhw.profile_id if name == "residential" else "")
    return use, air, source


def _context(record, policy, receipt, geometry, rows):
    """Shading-only neighbour context (see ``epsm._context``), or an empty context."""
    from epsm_core.specs.context import ContextSpec

    from ._context import context_spec, lake_context_rows

    if policy.context_radius_m is None:
        return ContextSpec()
    if rows is None:
        rows = lake_context_rows(record, policy.context_radius_m)
    if rows is None:
        receipt.quality.append("Portable record without neighbour rows: no shading context")
        return ContextSpec()
    origin = receipt.identities["geometry_coordinate_transform"]["translation_origin_xy"]
    footprints = [part.footprint for part in geometry.parts]
    context, dropped = context_spec(
        rows, origin_xy=origin, target_footprints=footprints,
        min_height_m=policy.context_min_height_m, radius_m=policy.context_radius_m,
    )
    _field(receipt, "context_buildings", len(context.buildings), "reported_with_geometry_assumptions",
           f"Lake components within {policy.context_radius_m:g} m as shading-only neighbours; dropped {dropped}")
    return context


def _heat_pump_template(observed, era, receipt):
    """Data's heat-pump template, by the EPC pump type where Data supports it."""
    import inspect

    from epsm_data.templates import heating_delivery_template

    pump = getattr(observed, "heat_pump_type", None)
    typed = "heat_pump_type" in inspect.signature(heating_delivery_template).parameters
    if pump and typed:
        template = heating_delivery_template("heat_pump", heat_pump_type=pump, era=era)
    else:
        template = heating_delivery_template("heat_pump")
    receipt.identities["heating_delivery_template"] = template.template_id
    if pump:
        receipt.identities["heat_pump_type"] = pump
    return template


LATER_BUILD_ROLES = ("wall", "roof", "ground", "basement_wall", "intermediate_floor", "window", "airtightness")


def _single_family_later_build(record, policy, year, renovation_state, overrides, receipt):
    """Policy version 12: component states for an SE.06 house built under the 2009/2012 energy rules.

    Returns (component_states, component_sources), or None when the rule does not apply.
    Applies only to single-family SE.06 in the existing state with no caller-chosen components.
    """
    from epsm_data.classification import era_for_year

    if (
        not policy.single_family_se06_later_build
        or record.type != BuildingType.RESIDENTIAL_SINGLE_FAMILY
        or renovation_state != "existing"
        or era_for_year(year) != "SE.06"
        or overrides.get("component_states")
    ):
        return None
    observed = _observed_systems(record)
    carrier = observed.heating_carrier if observed else None
    electric = carrier in ("heat_pump", "electric_direct")
    if not (
        (electric and year >= policy.single_family_later_build_electric_year)
        or year >= policy.single_family_later_build_any_year
    ):
        return None
    rule = (
        "BBR 16 (BFS 2008:20) limit for electrically heated buildings from 2009"
        if electric and year < policy.single_family_later_build_any_year
        else "BBR 19 (BFS 2011:6) limits from 2012"
    )
    source = f"Policy version 12: built {year} under {rule}; SE.06 advanced catalogue values as the later-build representative"
    receipt.assumptions.append(
        f"Single-family SE.06 later-build envelope (policy version 12): built {year}, carrier {carrier}; "
        "advanced constructions, windows and airtightness with the observed ventilation. "
        "This is the as-built representative for houses under the tighter rules, not a renovation."
    )
    receipt.identities["single_family_later_build"] = {"year": year, "carrier": carrier, "rule": rule}
    return ({role: "advanced" for role in LATER_BUILD_ROLES}, {role: source for role in LATER_BUILD_ROLES})


def _school_earlier_build(record, policy, year, renovation_state, overrides, receipt):
    """Policy version 13: True for a school SE.06 built before the BBR 19 limits of 2012.

    Applies only to the existing state with no caller-chosen components.
    """
    from epsm_data.classification import era_for_year

    if (
        not policy.school_se06_earlier_build
        or record.type != BuildingType.SCHOOL
        or renovation_state != "existing"
        or era_for_year(year) != "SE.06"
        or year >= policy.school_earlier_build_before_year
        or overrides.get("component_states")
    ):
        return False
    receipt.assumptions.append(
        f"School SE.06 earlier-build envelope (policy version 13): built {year}, before the BBR 19 "
        f"(BFS 2011:6) limits of {policy.school_earlier_build_before_year}; the school SE.05 existing wall, "
        "roof and window with SE.06 ventilation, airtightness and operation"
    )
    receipt.identities["school_earlier_build"] = {
        "year": year,
        "before_year": policy.school_earlier_build_before_year,
        "donor_year": policy.school_earlier_build_donor_year,
    }
    return True


def _delivery(record, policy, receipt, era=None):
    from epsm_core import DeliverySpec, HeatingDeliverySpec

    observed = _observed_systems(record)
    carrier = observed.heating_carrier if observed else None
    if carrier is None:
        receipt.quality.append(
            "Heating carrier mixed/unavailable: model reports ideal thermal demand; no purchased-energy conversion"
        )
        return DeliverySpec()
    options = {
        "carrier": carrier,
        "source": "ubem_v1: carrier indicated by raw EPC energy fields; effective efficiency/COP assumption",
    }
    if carrier == "heat_pump":
        template = _heat_pump_template(observed, era, receipt)
        options = dict(template.values["delivery"]["heating"])
    if carrier == "fuel":
        options["efficiency"] = policy.fuel_efficiency
    receipt.assumptions.append(
        f"Heating carrier {carrier}; effective delivery parameters from "
        + ("the catalogue's heat-pump template" if carrier == "heat_pump" else "policy")
        + ", not calibrated performance"
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
                "context_rows",
            }:
                raise ValueError("Unknown model override")
            context_rows = overrides.pop("context_rows", None)
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
            component_states = overrides.get("component_states")
            component_sources = overrides.get("component_sources")
            later = _single_family_later_build(record, policy, int(year), renovation_state, overrides, receipt)
            if later is not None:
                component_states, component_sources = later
            fabric = resolve_building_archetype(
                category=record.type.value,
                construction_year=int(year),
                climate_zone=zone,
                ventilation=ventilation,
                default_state=renovation_state,
                component_states=component_states,
                component_sources=component_sources,
                tabula_reference_area_m2=area,
                conditioned_volume_m3=geometry.conditioned_volume_m3,
                operating_standard=policy.operating_standard,
            )
            if _school_earlier_build(record, policy, int(year), renovation_state, overrides, receipt):
                donor = resolve_building_archetype(
                    category=record.type.value,
                    construction_year=policy.school_earlier_build_donor_year,
                    climate_zone=zone,
                    ventilation=ventilation,
                    default_state="existing",
                    tabula_reference_area_m2=area,
                    conditioned_volume_m3=geometry.conditioned_volume_m3,
                    operating_standard=policy.operating_standard,
                )
                fabric = dict(
                    fabric,
                    envelope=fabric["envelope"].updated(
                        wall=donor["envelope"].wall, top=donor["envelope"].top
                    ),
                    glazing=donor["glazing"],
                    assignment=dict(
                        fabric["assignment"],
                        earlier_build_donor={
                            "archetype_id": donor["assignment"]["archetype_id"],
                            "era": donor["assignment"]["era"],
                            "roles": ["wall", "top", "window"],
                        },
                    ),
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
                    era=fabric["assignment"]["era"],
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
                era=fabric["assignment"]["era"],
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
                    field_path="facade.solar_shading_factor",
                    status="assumed",
                    source=f"epsm_data Sveby operating profile ({policy.solar_shading!r}); {policy.name}/{policy.version}",
                ),
                SourceRecord(
                    field_path="facade.default_wwr",
                    status="assumed",
                    source=f"epsm_data facade_assumptions; {policy.name}/{policy.version}"
                    if policy.catalogue_templates and "wwr" not in overrides
                    else f"{policy.name}/{policy.version}",
                ),
            ]
            context = _context(record, policy, receipt, geometry, context_rows)
            spec = BuildingSpec(
                identifier=record.building_id,
                geometry=geometry,
                context=context,
                load_reference_area_m2=area,
                facade=facade,
                envelope=fabric["envelope"].updated(
                    foundation=_foundation(record, fabric["envelope"], geometry, policy, receipt),
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
                delivery=_delivery(record, policy, receipt, fabric["assignment"]["era"]),
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
