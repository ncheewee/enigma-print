#!/usr/bin/env python3
"""Generate a simple multicolour-ready logo tile from rendered text.

Outputs aligned STL bodies:
- base STL: background plate
- text STL: raised text colour body

Import both STLs into Bambu Studio as one assembly/object and assign colours.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon
from shapely.ops import triangulate

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


def write_ascii_stl(path: Path, name: str, triangles: Iterable[Triangle]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"solid {name}\n")
        for triangle in triangles:
            normal = triangle_normal(triangle)
            handle.write(f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n")
            handle.write("    outer loop\n")
            for vertex in triangle:
                handle.write(f"      vertex {vertex[0]:.4f} {vertex[1]:.4f} {vertex[2]:.4f}\n")
            handle.write("    endloop\n")
            handle.write("  endfacet\n")
        handle.write(f"endsolid {name}\n")


def triangle_normal(triangle: Triangle) -> Vertex:
    a, b, c = triangle
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
    return (nx / length, ny / length, nz / length)


def render_logo_mask(text: str, width_px: int, height_px: int, font_path: str) -> Image.Image:
    image = Image.new("L", (width_px, height_px), 0)
    draw = ImageDraw.Draw(image)

    font_size = int(height_px * 0.26)
    small_size = int(height_px * 0.13)
    title_font = ImageFont.truetype(font_path, font_size)
    subtitle_font = ImageFont.truetype(font_path, small_size)

    title = text.upper()
    subtitle = "DAILY MYSTERY PRINTS"
    title_box = draw.textbbox((0, 0), title, font=title_font)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    title_w = title_box[2] - title_box[0]
    title_h = title_box[3] - title_box[1]
    subtitle_w = subtitle_box[2] - subtitle_box[0]

    while title_w > width_px * 0.78 and font_size > 12:
        font_size -= 2
        title_font = ImageFont.truetype(font_path, font_size)
        title_box = draw.textbbox((0, 0), title, font=title_font)
        title_w = title_box[2] - title_box[0]
        title_h = title_box[3] - title_box[1]

    y_title = height_px * 0.34 - title_h / 2
    draw.text(((width_px - title_w) / 2, y_title), title, fill=255, font=title_font)
    draw.text(((width_px - subtitle_w) / 2, height_px * 0.64), subtitle, fill=210, font=subtitle_font)

    # Simple OPUS mark: four bars under the main word for recognisable geometry.
    bar_w = width_px * 0.11
    gap = width_px * 0.025
    total = bar_w * 4 + gap * 3
    x = (width_px - total) / 2
    y = height_px * 0.77
    for index in range(4):
        draw.rounded_rectangle((x + index * (bar_w + gap), y, x + index * (bar_w + gap) + bar_w, y + 8), radius=4, fill=255)

    return image


def mask_to_contour_solids(mask: Image.Image, width_mm: float, height_mm: float, base_z: float, top_z: float) -> List[Triangle]:
    array = np.array(mask)
    _, threshold = cv2.threshold(array, 127, 255, cv2.THRESH_BINARY)
    contours, hierarchy = cv2.findContours(threshold, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []

    width_px, height_px = mask.size
    hierarchy = hierarchy[0]
    triangles: List[Triangle] = []

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
            for part in polygon.geoms:
                triangles.extend(extrude_polygon(part, base_z, top_z))
        else:
            triangles.extend(extrude_polygon(polygon, base_z, top_z))
    return triangles


def contour_to_points(contour, width_px: int, height_px: int, width_mm: float, height_mm: float) -> List[Tuple[float, float]]:
    points = []
    for item in contour[:, 0, :]:
        x_px, y_px = float(item[0]), float(item[1])
        points.append((x_px / width_px * width_mm, (height_px - y_px) / height_px * height_mm))
    return points


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
                tri_top = (vertex(coords[0], z1), vertex(coords[index], z1), vertex(coords[index + 1], z1))
                tri_bottom = (vertex(coords[index + 1], z0), vertex(coords[index], z0), vertex(coords[0], z0))
                if triangle_area(tri_top) > 0.000001:
                    triangles.append(tri_top)
                    triangles.append(tri_bottom)

    rings = [list(polygon.exterior.coords[:-1]), *[list(ring.coords[:-1]) for ring in polygon.interiors]]
    for ring in rings:
        for index, point in enumerate(ring):
            nxt = ring[(index + 1) % len(ring)]
            triangles.append((vertex(point, z0), vertex(nxt, z0), vertex(nxt, z1)))
            triangles.append((vertex(point, z0), vertex(nxt, z1), vertex(point, z1)))
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


def write_preview(path: Path, mask: Image.Image, width_mm: float, height_mm: float) -> None:
    preview = Image.new("RGB", mask.size, "#173f3a")
    text_layer = Image.new("RGB", mask.size, "#f8f4df")
    preview.paste(text_layer, mask=mask)
    preview = preview.resize((int(width_mm * 8), int(height_mm * 8)))
    preview.save(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a multicolour text logo tile.")
    parser.add_argument("--text", default="Project Opus")
    parser.add_argument("--out", default="generated/logo/project-opus")
    parser.add_argument("--width", type=float, default=80.0)
    parser.add_argument("--height", type=float, default=50.0)
    parser.add_argument("--base-thickness", type=float, default=2.4)
    parser.add_argument("--text-height", type=float, default=0.8)
    parser.add_argument("--resolution", type=int, default=320)
    parser.add_argument("--font", default="/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    width_px = args.resolution
    height_px = int(args.resolution * args.height / args.width)
    mask = render_logo_mask(args.text, width_px, height_px, args.font)
    write_preview(out / "preview.png", mask, args.width, args.height)
    mask.save(out / "text-mask.png")

    base_triangles = box_triangles(0, 0, args.width, args.height, 0, args.base_thickness)
    text_triangles = mask_to_contour_solids(mask, args.width, args.height, args.base_thickness, args.base_thickness + args.text_height)
    write_ascii_stl(out / "project-opus-base.stl", "project_opus_base", base_triangles)
    write_ascii_stl(out / "project-opus-text.stl", "project_opus_text", text_triangles)

    manifest = {
        "name": args.text,
        "mode": "multicolour-logo-tile",
        "createdAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "dimensionsMm": {"width": args.width, "height": args.height, "totalHeight": args.base_thickness + args.text_height},
        "files": ["project-opus-base.stl", "project-opus-text.stl", "preview.png", "text-mask.png"],
        "bambuStudio": "Import base and text STL together as one object/assembly, then assign different filament colours.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated multicolour logo tile in {out}")
    print(out / "project-opus-base.stl")
    print(out / "project-opus-text.stl")


if __name__ == "__main__":
    main()
