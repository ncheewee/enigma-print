#!/usr/bin/env python3
"""Generate a minimal two-colour 3MF: rectangular base plus raised text."""

from __future__ import annotations

import argparse
import json
import math
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon
from shapely.ops import triangulate

Point = Tuple[float, float]
Vertex = Tuple[float, float, float]
Triangle = Tuple[Vertex, Vertex, Vertex]


def box_triangles(x0: float, y0: float, x1: float, y1: float, z0: float, z1: float) -> List[Triangle]:
    p000 = (x0, y0, z0)
    p100 = (x1, y0, z0)
    p110 = (x1, y1, z0)
    p010 = (x0, y1, z0)
    p001 = (x0, y0, z1)
    p101 = (x1, y0, z1)
    p111 = (x1, y1, z1)
    p011 = (x0, y1, z1)
    return [
        (p001, p101, p111), (p001, p111, p011),
        (p010, p110, p100), (p010, p100, p000),
        (p000, p100, p101), (p000, p101, p001),
        (p100, p110, p111), (p100, p111, p101),
        (p110, p010, p011), (p110, p011, p111),
        (p010, p000, p001), (p010, p001, p011),
    ]


def render_text_polygons(text: str, width_mm: float, height_mm: float, resolution: int, font_path: str) -> List[Polygon]:
    width_px = resolution
    height_px = int(resolution * height_mm / width_mm)
    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)
    words = text.upper().split()
    lines = words if len(words) <= 2 else [" ".join(words[:-1]), words[-1]]

    line_gap = height_px * 0.03
    rendered = []
    for line in lines:
        font_size = int(height_px * 0.45)
        while font_size > 12:
            font = ImageFont.truetype(font_path, font_size)
            box = draw.textbbox((0, 0), line, font=font)
            text_w = box[2] - box[0]
            text_h = box[3] - box[1]
            if text_w <= width_px * 0.90:
                rendered.append((line, font, text_w, text_h, box))
                break
            font_size -= 2

    total_h = sum(item[3] for item in rendered) + line_gap * (len(rendered) - 1)
    y = (height_px - total_h) / 2
    for line, font, text_w, text_h, box in rendered:
        draw.text(((width_px - text_w) / 2 - box[0], y - box[1]), line, fill=255, font=font)
        y += text_h + line_gap

    array = np.array(mask)
    _, threshold = cv2.threshold(array, 127, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    threshold = cv2.dilate(threshold, kernel, iterations=1)

    contours, hierarchy = cv2.findContours(threshold, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []

    hierarchy = hierarchy[0]
    polygons: List[Polygon] = []
    for index, contour in enumerate(contours):
        if hierarchy[index][3] != -1:
            continue
        shell = contour_to_points(contour, width_px, height_px, width_mm, height_mm)
        holes = [
            contour_to_points(contours[child_index], width_px, height_px, width_mm, height_mm)
            for child_index, item in enumerate(hierarchy)
            if item[3] == index and len(contours[child_index]) >= 3
        ]
        polygon = Polygon(shell, holes)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty:
            continue
        if polygon.geom_type == "MultiPolygon":
            polygons.extend([part for part in polygon.geoms if part.area > 0])
        else:
            polygons.append(polygon)
    return polygons


def contour_to_points(contour, width_px: int, height_px: int, width_mm: float, height_mm: float) -> List[Point]:
    return [
        (float(item[0]) / width_px * width_mm, (height_px - float(item[1])) / height_px * height_mm)
        for item in contour[:, 0, :]
    ]


def extrude_polygon(polygon: Polygon, z0: float, z1: float) -> List[Triangle]:
    triangles: List[Triangle] = []
    for tri in triangulate(polygon):
        clipped = tri.intersection(polygon)
        if clipped.is_empty:
            continue
        parts = list(clipped.geoms) if clipped.geom_type == "MultiPolygon" else [clipped]
        for part in parts:
            if part.geom_type != "Polygon" or part.area <= 0:
                continue
            coords = list(part.exterior.coords[:-1])
            for index in range(1, len(coords) - 1):
                triangles.append((vertex(coords[0], z1), vertex(coords[index], z1), vertex(coords[index + 1], z1)))
                triangles.append((vertex(coords[index + 1], z0), vertex(coords[index], z0), vertex(coords[0], z0)))

    for ring in [list(polygon.exterior.coords[:-1]), *[list(ring.coords[:-1]) for ring in polygon.interiors]]:
        for index, point in enumerate(ring):
            nxt = ring[(index + 1) % len(ring)]
            triangles.append((vertex(point, z0), vertex(nxt, z0), vertex(nxt, z1)))
            triangles.append((vertex(point, z0), vertex(nxt, z1), vertex(point, z1)))
    return triangles


def vertex(point: Point, z: float) -> Vertex:
    return (float(point[0]), float(point[1]), z)


def write_3mf(path: Path, base_triangles: Sequence[Triangle], text_triangles: Sequence[Triangle]) -> None:
    model_xml = build_model_xml(base_triangles, text_triangles)
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types_xml)
        package.writestr("_rels/.rels", rels_xml)
        package.writestr("3D/3dmodel.model", model_xml)


def build_model_xml(base_triangles: Sequence[Triangle], text_triangles: Sequence[Triangle]) -> str:
    base_object = object_xml(2, "base_colour_1", base_triangles, material_index=0)
    text_object = object_xml(3, "text_colour_2", text_triangles, material_index=1)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <basematerials id="1">
      <base name="Base colour" displaycolor="#173F3AFF"/>
      <base name="Text colour" displaycolor="#F8F4DFFF"/>
    </basematerials>
    {base_object}
    {text_object}
  </resources>
  <build>
    <item objectid="2"/>
    <item objectid="3"/>
  </build>
</model>
"""


def object_xml(object_id: int, name: str, triangles: Sequence[Triangle], material_index: int) -> str:
    vertices, triangle_indices = indexed_mesh(triangles)
    vertices_xml = "\n".join(f'        <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in vertices)
    triangles_xml = "\n".join(
        f'        <triangle v1="{a}" v2="{b}" v3="{c}" pid="1" p1="{material_index}" p2="{material_index}" p3="{material_index}"/>'
        for a, b, c in triangle_indices
    )
    return f"""<object id="{object_id}" type="model" name="{name}" pid="1" pindex="{material_index}">
      <mesh>
        <vertices>
{vertices_xml}
        </vertices>
        <triangles>
{triangles_xml}
        </triangles>
      </mesh>
    </object>"""


def indexed_mesh(triangles: Sequence[Triangle]):
    vertices: List[Vertex] = []
    vertex_index = {}
    triangle_indices = []
    for triangle in triangles:
        indices = []
        for point in triangle:
            key = (round(point[0], 5), round(point[1], 5), round(point[2], 5))
            if key not in vertex_index:
                vertex_index[key] = len(vertices)
                vertices.append(key)
            indices.append(vertex_index[key])
        triangle_indices.append(tuple(indices))
    return vertices, triangle_indices


def write_preview(path: Path, text_polygons: Sequence[Polygon], width: float, height: float) -> None:
    scale = 10
    image = Image.new("RGB", (int(width * scale), int(height * scale)), "#173f3a")
    draw = ImageDraw.Draw(image)
    for polygon in text_polygons:
        coords = [(x * scale, (height - y) * scale) for x, y in polygon.exterior.coords]
        draw.polygon(coords, fill="#f8f4df")
        for ring in polygon.interiors:
            hole = [(x * scale, (height - y) * scale) for x, y in ring.coords]
            draw.polygon(hole, fill="#173f3a")
    image.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate minimal two-colour 3MF test.")
    parser.add_argument("--text", default="Project Opus")
    parser.add_argument("--out", default="generated/logo/simple-multicolor-3mf")
    parser.add_argument("--width", type=float, default=40.0)
    parser.add_argument("--height", type=float, default=40.0)
    parser.add_argument("--base-thickness", type=float, default=2.4)
    parser.add_argument("--text-height", type=float, default=1.6)
    parser.add_argument("--resolution", type=int, default=360)
    parser.add_argument("--font", default="/System/Library/Fonts/Supplemental/Impact.ttf")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    text_polygons = render_text_polygons(args.text, args.width, args.height, args.resolution, args.font)
    base_triangles = box_triangles(0, 0, args.width, args.height, 0, args.base_thickness)
    text_triangles: List[Triangle] = []
    for polygon in text_polygons:
        text_triangles.extend(extrude_polygon(polygon, args.base_thickness, args.base_thickness + args.text_height))
    write_3mf(out / "project-opus-simple-multicolor.3mf", base_triangles, text_triangles)
    write_preview(out / "preview.png", text_polygons, args.width, args.height)
    manifest = {
        "name": args.text,
        "mode": "simple-multicolor-3mf",
        "createdAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "files": ["project-opus-simple-multicolor.3mf", "preview.png"],
        "dimensionsMm": {"width": args.width, "height": args.height, "totalHeight": args.base_thickness + args.text_height},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated simple multicolour 3MF in {out}")


if __name__ == "__main__":
    main()
