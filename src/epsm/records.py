"""Explicit evidence-to-model conversion, with no database access."""

from copy import deepcopy


def _value(record, name, default=None):
    return record.get(name, default) if isinstance(record, dict) else getattr(record, name, default)


def building_from_record(building_type, record, **options):
    geometry = _value(record, "geometry")
    facts = _value(record, "facts", {})
    options.setdefault("identifier", str(_value(record, "building_id", "building")))
    storeys = options.pop("storeys", _value(record, "storeys", facts.get("storeys")))
    storey_height = options.pop("storey_height_m", facts.get("storey_height_m"))
    if geometry is not None and isinstance(geometry, dict):
        from shapely.geometry import shape
        geometry = shape(geometry)
    if geometry is not None and storeys is not None and storey_height is not None:
        building = building_type.from_footprint(geometry, storeys=storeys,
                                                storey_height_m=storey_height, **options)
    else:
        building = building_type.empty(**options)
    # Retain a bounded portable evidence view; no connection strings or live handles.
    building._source_record = dict(
        building_id=_value(record, "building_id"), dataset_id=_value(record, "dataset_id"),
        facts=deepcopy(facts), atemp_m2=_value(record, "atemp_m2"), storeys=storeys,
        observations=deepcopy(_value(record, "observations", ())),
        receipt=(_value(record, "receipt").to_dict() if hasattr(_value(record, "receipt"), "to_dict")
                 else deepcopy(_value(record, "receipt"))),
        geometry=geometry.__geo_interface__ if geometry is not None else None,
        requirements=[name for name, value in (("footprint", geometry), ("storeys", storeys),
                                                ("storey_height_m", storey_height)) if value is None],
    )
    return building


def compare_record(building, record):
    """Report area/storey differences without treating reported EPC values as measurements."""
    if record is None:
        raise ValueError("Supply a BuildingRecord or create the Building.from_record(record)")
    geometry = building.geometry
    area = geometry.conditioned_floor_area_m2 if geometry is not None else None
    parts = geometry.parts if geometry is not None else ()
    floors = sum(p.floors for p in parts) if parts else None
    rows = []
    for field, modeled, observed, unit in (
        ("heated_area", area, _value(record, "atemp_m2"), "m2"),
        ("storeys", floors, _value(record, "storeys"), "count"),
    ):
        rows.append(dict(property=field, model=modeled, observed=observed, unit=unit,
                         evidence_kind="reported", dataset_id=_value(record, "dataset_id"),
                         difference=None if modeled is None or observed is None else modeled - observed,
                         status="missing" if modeled is None or observed is None else "comparable"))
    return rows
