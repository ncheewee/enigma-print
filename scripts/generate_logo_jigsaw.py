#!/usr/bin/env python3
"""Generate a multicolour text logo split into jigsaw pieces."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import random
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyjigsaw import jigsawfactory
from shapely.geometry import Polygon
from shapely.ops import triangulate
from svgpathtools import svg2paths

Point = Tuple[float, float]
Vertex = Tuple[float, float, float]
Triangle = Tuple[Vertex, Vertex, Vertex]


def build_cut_paths(width: float, height: float, rows: int, cols: int, seed: int) -> List[str]:
    random.seed(seed)
    with contextlib.redirect_stdout(io.StringIO()):
        cut = jigsawfactory.Cut(rows, cols, abs_width=width, abs_height=height, stroke_color="black", fill_color="white")
    root = ET.fromstring(cut.svg_template.strip())
    return [element.attrib["d"] for element in root.iter() if element.tag.endswith("path")]


def sample_svg_path(path_d: str, samples_per_segment: int) -> List[Point]:
    with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False) as handle:
        handle.write(f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{path_d}"/></svg>')
        temp_path = Path(handle.name)
    try:
        paths, _ = svg2paths(str(temp_path))
    finally:
        temp_path.unlink(missing_ok=True)

    points: List[Point] = []
    for segment in paths[0]:
        for index in range(samples_per_segment):
            value = segment.point(index / samples_per_segment)
            points.append((value.real, value.imag))
    return ensure_ccw(dedupe(points))


def clean_piece_polygon(points: Sequence[Point], shrink: float, corner_radius: float) -> Polygon:
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if shrink > 0:
        polygon = polygon.buffer(-shrink, join_style="round", resolution=12)
    if corner_radius > 0:
        polygon = polygon.buffer(-corner_radius, join_style="round", resolution=12).buffer(
            corner_radius, join_style="round", resolution=12
        )
    if polygon.geom_type == "MultiPolygon":
        polygon = max(polygon.geoms, key=lambda item: item.area)
    return polygon


def render_text_polygons(
    text: str,
    width_mm: float,
    height_mm: float,
    resolution: int,
    font_path: str,
    target_width_ratio: float,
    thicken_px: int,
) -> List[Polygon]:
    width_px = resolution
    height_px = int(resolution * height_mm / width_mm)
    mask = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(mask)

    words = text.upper().split()
    lines = words if len(words) <= 2 else [" ".join(words[:-1]), words[-1]]
    target_height = height_px * 0.82
    line_gap = height_px * 0.02
    rendered = []

    for line in lines:
        font_size = int(height_px * (0.48 if len(lines) == 2 else 0.62))
        while font_size > 12:
            font = ImageFont.truetype(font_path, font_size)
            box = draw.textbbox((0, 0), line, font=font)
            text_w = box[2] - box[0]
            text_h = box[3] - box[1]
            if text_w <= width_px * target_width_ratio:
                rendered.append((line, font, text_w, text_h, box))
                break
            font_size -= 2

    total_h = sum(item[3] for item in rendered) + line_gap * (len(rendered) - 1)
    if total_h > target_height:
        scale = target_height / total_h
        rendered = []
        for line in lines:
            font_size = int(height_px * (0.48 if len(lines) == 2 else 0.62) * scale)
            font = ImageFont.truetype(font_path, max(12, font_size))
            box = draw.textbbox((0, 0), line, font=font)
            rendered.append((line, font, box[2] - box[0], box[3] - box[1], box))
        total_h = sum(item[3] for item in rendered) + line_gap * (len(rendered) - 1)

    y = (height_px - total_h) / 2
    for line, font, text_w, text_h, box in rendered:
        draw.text(((width_px - text_w) / 2 - box[0], y - box[1]), line, fill=255, font=font)
        y += text_h + line_gap

    array = np.array(mask)
    _, threshold = cv2.threshold(array, 127, 255, cv2.THRESH_BINARY)
    if thicken_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thicken_px * 2 + 1, thicken_px * 2 + 1))
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
        if len(shell) < 3:
            continue
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
                top_tri = (vertex(coords[0], z1), vertex(coords[index], z1), vertex(coords[index + 1], z1))
                bottom_tri = (vertex(coords[index + 1], z0), vertex(coords[index], z0), vertex(coords[0], z0))
                if triangle_area(top_tri) > 0.000001:
                    triangles.append(top_tri)
                    triangles.append(bottom_tri)

    rings = [list(polygon.exterior.coords[:-1]), *[list(ring.coords[:-1]) for ring in polygon.interiors]]
    for ring in rings:
        for index, point in enumerate(ring):
            nxt = ring[(index + 1) % len(ring)]
            triangles.append((vertex(point, z0), vertex(nxt, z0), vertex(nxt, z1)))
            triangles.append((vertex(point, z0), vertex(nxt, z1), vertex(point, z1)))
    return triangles


def extrude_piece(polygon: Polygon, thickness: float, bevel_height: float, bevel_inset: float) -> List[Triangle]:
    if bevel_height <= 0 or bevel_inset <= 0:
        return extrude_polygon(polygon, 0, thickness)

    bevel_height = min(bevel_height, thickness / 3)
    inset = polygon.buffer(-bevel_inset, join_style="round", resolution=8)
    if inset.is_empty:
        return extrude_polygon(polygon, 0, thickness)
    if inset.geom_type == "MultiPolygon":
        inset = max(inset.geoms, key=lambda item: item.area)

    sample_count = max(160, int(max(polygon.exterior.length, inset.exterior.length) / 0.35))
    nominal = resample_exterior(polygon, sample_count)
    inner = resample_exterior(inset, sample_count)

    triangles: List[Triangle] = []
    triangles.extend(cap(inner, 0, upward=False))
    triangles.extend(connect_layers(inner, nominal, 0, bevel_height))
    triangles.extend(connect_layers(nominal, nominal, bevel_height, thickness - bevel_height))
    triangles.extend(connect_layers(nominal, inner, thickness - bevel_height, thickness))
    triangles.extend(cap(inner, thickness, upward=True))
    return triangles


def resample_exterior(polygon: Polygon, count: int) -> List[Point]:
    ring = polygon.exterior
    points = []
    for index in range(count):
        point = ring.interpolate(ring.length * index / count)
        points.append((float(point.x), float(point.y)))
    return ensure_ccw(dedupe(points))


def cap(points: Sequence[Point], z: float, upward: bool) -> List[Triangle]:
    polygon = Polygon(points)
    triangles: List[Triangle] = []
    for tri in triangulate(polygon):
        clipped = tri.intersection(polygon)
        if clipped.is_empty or clipped.geom_type != "Polygon":
            continue
        coords = list(clipped.exterior.coords[:-1])
        for index in range(1, len(coords) - 1):
            if upward:
                triangles.append((vertex(coords[0], z), vertex(coords[index], z), vertex(coords[index + 1], z)))
            else:
                triangles.append((vertex(coords[index + 1], z), vertex(coords[index], z), vertex(coords[0], z)))
    return triangles


def connect_layers(lower: Sequence[Point], upper: Sequence[Point], z0: float, z1: float) -> List[Triangle]:
    triangles: List[Triangle] = []
    for index, point in enumerate(lower):
        nxt = (index + 1) % len(lower)
        triangles.append((vertex(point, z0), vertex(lower[nxt], z0), vertex(upper[nxt], z1)))
        triangles.append((vertex(point, z0), vertex(upper[nxt], z1), vertex(upper[index], z1)))
    return triangles


def vertex(point: Tuple[float, float], z: float) -> Vertex:
    return (float(point[0]), float(point[1]), z)


def triangle_area(triangle: Triangle) -> float:
    a, b, c = triangle
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    return math.sqrt(nx * nx + ny * ny + nz * nz) / 2


def write_ascii_stl(path: Path, name: str, triangles: Iterable[Triangle]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"solid {name}\n")
        for triangle in triangles:
            normal = triangle_normal(triangle)
            handle.write(f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n")
            handle.write("    outer loop\n")
            for item in triangle:
                handle.write(f"      vertex {item[0]:.4f} {item[1]:.4f} {item[2]:.4f}\n")
            handle.write("    endloop\n")
            handle.write("  endfacet\n")
        handle.write(f"endsolid {name}\n")


def write_3mf(path: Path, base_triangles: Sequence[Triangle], text_triangles: Sequence[Triangle]) -> None:
    model_xml = build_3mf_model(base_triangles, text_triangles)
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


def build_3mf_model(base_triangles: Sequence[Triangle], text_triangles: Sequence[Triangle]) -> str:
    base_mesh = mesh_xml(2, "base_colour_1", base_triangles, 0)
    text_mesh = mesh_xml(3, "text_colour_2", text_triangles, 1)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US"
  xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
  xmlns:m="http://schemas.microsoft.com/3dmanufacturing/material/2015/02">
  <metadata name="Title">Enigma Print multicolour piece</metadata>
  <resources>
    <m:basematerials id="1">
      <m:base name="Base colour" displaycolor="#173F3AFF"/>
      <m:base name="Text colour" displaycolor="#F8F4DFFF"/>
    </m:basematerials>
    {base_mesh}
    {text_mesh}
  </resources>
  <build>
    <item objectid="2"/>
    <item objectid="3"/>
  </build>
</model>
"""


def mesh_xml(object_id: int, name: str, triangles: Sequence[Triangle], material_index: int) -> str:
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

    vertices_xml = "\n".join(
        f'        <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in vertices
    )
    triangles_xml = "\n".join(
        f'        <triangle v1="{a}" v2="{b}" v3="{c}" pid="1" p1="{material_index}"/>'
        for a, b, c in triangle_indices
    )
    return f"""<object id="{object_id}" type="model" name="{name}">
      <mesh>
        <vertices>
{vertices_xml}
        </vertices>
        <triangles>
{triangles_xml}
        </triangles>
      </mesh>
    </object>"""


def triangle_normal(triangle: Triangle) -> Vertex:
    a, b, c = triangle
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
    return (nx / length, ny / length, nz / length)


def ensure_ccw(points: List[Point]) -> List[Point]:
    return points if signed_area(points) > 0 else list(reversed(points))


def signed_area(points: Sequence[Point]) -> float:
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    return area / 2


def dedupe(points: Sequence[Point]) -> List[Point]:
    output: List[Point] = []
    for point in points:
        if not output or math.hypot(output[-1][0] - point[0], output[-1][1] - point[1]) > 0.001:
            output.append(point)
    if len(output) > 1 and math.hypot(output[0][0] - output[-1][0], output[0][1] - output[-1][1]) < 0.001:
        output.pop()
    return output


def write_preview(path: Path, piece_polygons: Sequence[Polygon], text_polygons: Sequence[Polygon], width: float, height: float) -> None:
    scale = 8
    image = Image.new("RGB", (int(width * scale), int(height * scale)), "#173f3a")
    draw = ImageDraw.Draw(image)
    for polygon in piece_polygons:
        coords = [(x * scale, (height - y) * scale) for x, y in polygon.exterior.coords]
        draw.line(coords, fill="#d1a24d", width=2, joint="curve")
    for polygon in text_polygons:
        coords = [(x * scale, (height - y) * scale) for x, y in polygon.exterior.coords]
        draw.polygon(coords, fill="#f8f4df")
        for ring in polygon.interiors:
            hole = [(x * scale, (height - y) * scale) for x, y in ring.coords]
            draw.polygon(hole, fill="#173f3a")
    image.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate multicolour jigsaw logo pieces.")
    parser.add_argument("--text", default="Project Opus")
    parser.add_argument("--out", default="generated/logo/project-opus-jigsaw-2x2")
    parser.add_argument("--width", type=float, default=72.0)
    parser.add_argument("--height", type=float, default=72.0)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--cols", type=int, default=2)
    parser.add_argument("--base-thickness", type=float, default=2.4)
    parser.add_argument("--text-height", type=float, default=2.0)
    parser.add_argument("--text-embed", type=float, default=0.08, help="How far raised text overlaps into the base in mm")
    parser.add_argument("--shrink", type=float, default=0.1)
    parser.add_argument("--corner-radius", type=float, default=0.5)
    parser.add_argument("--bevel-height", type=float, default=1.0)
    parser.add_argument("--bevel-inset", type=float, default=0.25)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--resolution", type=int, default=360)
    parser.add_argument("--font", default="/System/Library/Fonts/Supplemental/Impact.ttf")
    parser.add_argument("--text-width-ratio", type=float, default=0.92)
    parser.add_argument("--text-thicken-px", type=int, default=3)
    parser.add_argument("--format", choices=["stl", "3mf"], default="stl")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    path_ds = build_cut_paths(args.width, args.height, args.rows, args.cols, args.seed)
    pieces = [
        clean_piece_polygon(sample_svg_path(path_d, args.samples), args.shrink, args.corner_radius)
        for path_d in path_ds
    ]
    text_polygons = render_text_polygons(
        args.text,
        args.width,
        args.height,
        args.resolution,
        args.font,
        args.text_width_ratio,
        args.text_thicken_px,
    )
    write_preview(out / "preview.png", pieces, text_polygons, args.width, args.height)

    manifest_files = ["preview.png"]
    for index, piece in enumerate(pieces, start=1):
        extension = "3mf" if args.format == "3mf" else "stl"
        piece_name = f"piece-{index:02d}.{extension}"
        base_triangles = extrude_piece(piece, args.base_thickness, args.bevel_height, args.bevel_inset)
        text_triangles: List[Triangle] = []

        for text_polygon in text_polygons:
            clipped = text_polygon.intersection(piece)
            if clipped.is_empty:
                continue
            parts = list(clipped.geoms) if clipped.geom_type == "MultiPolygon" else [clipped]
            for part in parts:
                if part.geom_type == "Polygon" and part.area > 0:
                    text_triangles.extend(
                        extrude_polygon(part, args.base_thickness - args.text_embed, args.base_thickness + args.text_height)
                    )

        if args.format == "3mf":
            write_3mf(out / piece_name, base_triangles, text_triangles)
        else:
            write_ascii_stl(out / piece_name, f"piece_{index:02d}", [*base_triangles, *text_triangles])
        manifest_files.append(piece_name)

    manifest = {
        "name": args.text,
        "mode": "multicolour-3mf-jigsaw-logo" if args.format == "3mf" else "single-object-jigsaw-logo",
        "createdAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "dimensionsMm": {
            "width": args.width,
            "height": args.height,
            "totalHeight": args.base_thickness + args.text_height,
        },
        "pieceCount": len(pieces),
        "files": manifest_files,
        "bambuStudio": "Each file is one physical jigsaw piece. 3MF outputs contain base and raised text material bodies with preset colours.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated multicolour jigsaw logo in {out}")


if __name__ == "__main__":
    main()
