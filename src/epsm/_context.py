"""Shading-only neighbour context for the record route (policy version 6).

Neighbours are lake building components within ``radius_m`` of the target footprint,
each extruded to its representative height. They only cast shadows: no thermal
coupling and no party walls. The rules, in order:

1. components of the target building itself are excluded by the caller or query;
2. a component that overlaps the target's *prepared* model footprint is dropped
   (contact with the model is a party-wall question, not shading; the prepared
   footprint can differ from the source outline after cleanup);
3. components lower than ``min_height_m`` are dropped;
4. the rest are placed tallest first; a lower component loses any plan area that a
   taller one already covers, so context footprints never overlap each other;
5. outlines are simplified and short edges removed, because EnergyPlus rejects
   near-coincident vertices.

Rows are ``{"id": str, "height_m": float, "geometry": shapely polygon or WKT}`` in
EPSG:3006. ``lake_context_rows`` reads them from the published ``gis.components``
layer through the record's database connection; portable records take them from the
caller (``overrides["context_rows"]``).
"""

from __future__ import annotations

import math

SIMPLIFY_M = 0.3
CLEARANCE_M = 0.1
MIN_EDGE_M = 0.1
MIN_PART_AREA_M2 = 1.0
TARGET_OVERLAP_M2 = 1e-6

_SQL = """SELECT component_external_id AS id, representative_height_m AS height_m, ST_AsText(geom) AS wkt
          FROM gis.components
          WHERE geometry_valid AND representative_height_m > 0
            AND ST_DWithin(geom, ST_GeomFromText(%(geometry)s, 3006), %(radius)s)
            AND building_external_id <> %(building)s"""


def lake_context_rows(record, radius_m):
    """Neighbour component rows for a database-backed record, or None for a portable one."""
    url = getattr(record, "_database_url", None)
    if not url or record.geometry is None:
        return None
    from epsm_db import Database

    with Database(url)._read() as (connection, _):
        rows = connection.execute(
            _SQL, {"geometry": record.geometry.wkt, "radius": float(radius_m), "building": record.building_id}
        ).fetchall()
    return [{"id": r["id"], "height_m": float(r["height_m"]), "geometry": r["wkt"]} for r in rows]


def _polygons(geometry):
    from shapely import wkt
    from shapely.geometry import Polygon

    if isinstance(geometry, str):
        geometry = wkt.loads(geometry)
    if isinstance(geometry, Polygon):
        return [geometry]
    return [g for g in getattr(geometry, "geoms", ()) if isinstance(g, Polygon)]


def _clean(polygon):
    from shapely.geometry import Polygon

    polygon = polygon.simplify(SIMPLIFY_M)
    if polygon.is_empty or polygon.geom_type != "Polygon":
        return None
    points = []
    for point in list(polygon.exterior.coords)[:-1]:
        if not points or math.dist(point, points[-1]) >= MIN_EDGE_M:
            points.append(point)
    if len(points) > 3 and math.dist(points[0], points[-1]) < MIN_EDGE_M:
        points.pop()
    if len(points) < 3:
        return None
    cleaned = Polygon(points).buffer(0)
    return cleaned if cleaned.geom_type == "Polygon" and cleaned.area > MIN_PART_AREA_M2 else None


def context_spec(rows, *, origin_xy, target_footprints, min_height_m, radius_m):
    """``(ContextSpec, dropped counts)`` for rows in EPSG:3006 around a target.

    ``target_footprints`` are the prepared model footprints in the model frame, which is
    EPSG:3006 translated by ``-origin_xy``.
    """
    from epsm_core.specs.context import ContextBuilding, ContextSpec
    from epsm_core.specs.geometry import Footprint
    from shapely.affinity import translate
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    target = unary_union([Polygon(f.exterior, f.holes) for f in target_footprints])
    ox, oy = origin_xy
    dropped = {"overlap": 0, "low": 0, "covered": 0}
    placed = target.buffer(CLEARANCE_M)
    buildings, shapes = [], []
    for row in sorted(rows, key=lambda r: -float(r["height_m"])):
        parts = [translate(p, xoff=-ox, yoff=-oy) for p in _polygons(row["geometry"])]
        if any(p.intersection(target).area > TARGET_OVERLAP_M2 for p in parts):
            dropped["overlap"] += 1
            continue
        if float(row["height_m"]) < min_height_m:
            dropped["low"] += 1
            continue
        kept = []
        for part in parts:
            remainder = part.simplify(SIMPLIFY_M).difference(placed.buffer(CLEARANCE_M)).buffer(0)
            for piece in getattr(remainder, "geoms", [remainder]):
                cleaned = _clean(piece) if piece.geom_type == "Polygon" else None
                if cleaned is not None and not any(cleaned.intersection(s).area > 1e-9 for s in shapes):
                    kept.append(cleaned)
        if not kept:
            dropped["covered"] += 1
            continue
        placed = placed.union(unary_union(kept))
        shapes.extend(kept)
        buildings.append(ContextBuilding(
            identifier=str(row["id"])[:120],
            footprints=tuple(Footprint(exterior=tuple(list(k.exterior.coords)[:-1])) for k in kept),
            height_m=float(row["height_m"]),
        ))
    generation = {"source": "gis.components", "radius_m": radius_m, "min_height_m": min_height_m, "dropped": dropped}
    return ContextSpec(buildings=tuple(buildings), generation=generation), dropped
