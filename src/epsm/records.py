"""Explicit evidence-to-model conversion, with no database access."""

from copy import deepcopy


def _value(record, name, default=None):
    return (
        record.get(name, default)
        if isinstance(record, dict)
        else getattr(record, name, default)
    )


def _record_view(record):
    if isinstance(record, dict) and "format" in record:
        if record["format"] != "epsm-record-1" or record.get("crs") != "EPSG:3006":
            raise ValueError("Expected EPSM record format 1 in EPSG:3006")
        try:
            from epsm_db import BuildingRecord
        except ImportError as error:
            raise ImportError(
                "Install epsm[database] to decode portable BuildingRecord evidence"
            ) from error
        return BuildingRecord.from_dict(record)
    return record


def building_from_record(building_type, record, **options):
    record = _record_view(record)
    geometry = _value(record, "geometry")
    facts = _value(record, "facts", {})
    source_crs = options.pop("source_crs", _value(record, "crs", "local_metres"))
    options.setdefault("identifier", str(_value(record, "building_id", "building")))
    observed_storeys = _value(record, "storeys", facts.get("storeys"))
    storeys = options.pop("storeys", observed_storeys)
    storey_height = options.pop("storey_height_m", facts.get("storey_height_m"))
    if geometry is not None and isinstance(geometry, dict):
        from shapely.geometry import shape

        geometry = shape(geometry)
    if geometry is not None and storeys is not None and storey_height is not None:
        building = building_type.from_footprint(
            geometry,
            storeys=storeys,
            storey_height_m=storey_height,
            source_crs=source_crs,
            **options,
        )
    else:
        building = building_type.empty(**options)
    # Keep the established comparison summary and the complete public DB envelope.
    # DB owns encoding dates/geometries and excluding connection/runtime fields.
    building._source_record = dict(
        building_id=_value(record, "building_id"),
        crs=source_crs,
        dataset_id=_value(record, "dataset_id"),
        facts=deepcopy(facts),
        atemp_m2=_value(record, "atemp_m2"),
        storeys=observed_storeys,
        archetype_assignments=deepcopy(_value(record, "archetype_assignments", ())),
        observations=deepcopy(_value(record, "observations", ())),
        receipt=(
            _value(record, "receipt").to_dict()
            if hasattr(_value(record, "receipt"), "to_dict")
            else deepcopy(_value(record, "receipt"))
        ),
        geometry=geometry.__geo_interface__ if geometry is not None else None,
        requirements=[
            name
            for name, value in (
                ("footprint", geometry),
                ("storeys", storeys),
                ("storey_height_m", storey_height),
            )
            if value is None
        ],
    )
    if hasattr(record, "to_dict"):
        portable = record.to_dict()
        if portable.get("format") == "epsm-record-1":
            building._source_record["portable_record"] = deepcopy(portable)
    return building


def compare_record(building, record):
    """Report area/storey differences without treating reported EPC values as measurements."""
    if record is None:
        raise ValueError(
            "Supply a BuildingRecord or create the Building.from_record(record)"
        )
    record = _record_view(record)
    geometry = building.geometry
    area = geometry.conditioned_floor_area_m2 if geometry is not None else None
    parts = geometry.parts if geometry is not None else ()
    floors = parts[0].floors if len(parts) == 1 else None
    rows = []
    for field, modeled, observed, unit in (
        ("heated_area", area, _value(record, "atemp_m2"), "m2"),
        ("storeys", floors, _value(record, "storeys"), "count"),
    ):
        comparable = field == "storeys" and modeled is not None and observed is not None
        rows.append(
            dict(
                property=field,
                model=modeled,
                observed=observed,
                unit=unit,
                evidence_kind="reported",
                dataset_id=_value(record, "dataset_id"),
                model_basis="conditioned_gross_floor_area"
                if field == "heated_area"
                else "storeys",
                observation_basis="reported_Atemp"
                if field == "heated_area"
                else "storeys",
                difference=modeled - observed if comparable else None,
                status="missing"
                if modeled is None or observed is None
                else "comparable"
                if comparable
                else "different_area_definitions",
            )
        )
    return rows
