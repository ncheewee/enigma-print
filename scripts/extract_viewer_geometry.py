#!/usr/bin/env python3
"""Extract lightweight 2D viewer outlines from generated 3MF puzzle pieces."""

from __future__ import annotations

import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union


NS = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}


def polygon_from_3mf(path: Path) -> Polygon:
    with zipfile.ZipFile(path) as package:
        model_name = next(name for name in package.namelist() if name.endswith(".model"))
        root = ET.fromstring(package.read(model_name))

    vertices = []
    for vertex in root.findall(".//m:vertices/m:vertex", NS):
        vertices.append(
            (
                float(vertex.attrib["x"]),
                float(vertex.attrib["y"]),
                float(vertex.attrib["z"]),
            )
        )

    triangles = []
    for tri in root.findall(".//m:triangles/m:triangle", NS):
        a = vertices[int(tri.attrib["v1"])]
        b = vertices[int(tri.attrib["v2"])]
        c = vertices[int(tri.attrib["v3"])]
        projected = [(a[0], a[1]), (b[0], b[1]), (c[0], c[1])]
        poly = Polygon(projected)
        if poly.is_valid and poly.area > 0.0001:
            triangles.append(poly)

    if not triangles:
        raise ValueError(f"No projectable triangles found in {path}")

    footprint = unary_union(triangles).buffer(0)
    if isinstance(footprint, MultiPolygon):
        footprint = max(footprint.geoms, key=lambda item: item.area)
    return footprint.simplify(0.08, preserve_topology=True)


def ring_points(polygon: Polygon) -> list[list[float]]:
    return [[round(x, 3), round(y, 3)] for x, y in polygon.exterior.coords[:-1]]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: extract_viewer_geometry.py <generated-project-dir>")

    project_dir = Path(sys.argv[1]).resolve()
    manifest_path = project_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    pieces = []
    for index, piece in enumerate(manifest["pieces"], start=1):
        filename = piece.get("filename") or f"piece-{index:02d}.3mf"
        piece_path = project_dir / filename
        polygon = polygon_from_3mf(piece_path)
        pieces.append(
            {
                "day": piece.get("day", index),
                "filename": filename,
                "outline": ring_points(polygon),
                "areaMm2": round(polygon.area, 2),
            }
        )

    combined = unary_union([Polygon(item["outline"]) for item in pieces]).buffer(0)
    if isinstance(combined, MultiPolygon):
        combined = max(combined.geoms, key=lambda item: item.area)

    minx, miny, maxx, maxy = combined.bounds
    payload = {
        "version": 1,
        "source": "3mf-projected-footprints",
        "project": manifest.get("name", project_dir.name),
        "bounds": [round(minx, 3), round(miny, 3), round(maxx, 3), round(maxy, 3)],
        "pieces": pieces,
        "combined": {
            "outline": ring_points(combined.simplify(0.08, preserve_topology=True)),
            "areaMm2": round(combined.area, 2),
        },
    }

    output_path = project_dir / "viewer-geometry.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
