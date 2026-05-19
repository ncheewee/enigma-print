#!/usr/bin/env python3
"""Generate jigsaw coupon STLs from pyjigsaw's SVG cut paths."""

from __future__ import annotations

import argparse
import contextlib
import io
import math
import random
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from pyjigsaw import jigsawfactory
from shapely.geometry import Polygon
from svgpathtools import parse_path
from svgpathtools import svg2paths

Point = Tuple[float, float]
Vertex = Tuple[float, float, float]
Triangle = Tuple[Vertex, Vertex, Vertex]


def build_cut_paths(width: float, height: float, rows: int, cols: int, seed: int) -> List[str]:
    random.seed(seed)
    with contextlib.redirect_stdout(io.StringIO()):
        cut = jigsawfactory.Cut(rows, cols, abs_width=width, abs_height=height, stroke_color="black", fill_color="white")

    root = ET.fromstring(cut.svg_template.strip())
    paths = []
    for element in root.iter():
        if element.tag.endswith("path"):
            paths.append(element.attrib["d"])
    return paths


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


def sample_shared_cut(path_d: str, samples_per_segment: int) -> List[Point]:
    path = parse_path(path_d)
    points: List[Point] = []
    # For the 1x2 coupon, pyjigsaw path 0 is:
    # top line, three cubic shared-cut segments, bottom line, left line.
    for segment in path[1:4]:
        for index in range(samples_per_segment):
            value = segment.point(index / samples_per_segment)
            points.append((value.real, value.imag))
    value = path[3].point(1)
    points.append((value.real, value.imag))
    return dedupe(points)


def offset_polyline(points: Sequence[Point], offset: float) -> List[Point]:
    output = []
    for index, point in enumerate(points):
        previous = points[max(0, index - 1)]
        nxt = points[min(len(points) - 1, index + 1)]
        dx = nxt[0] - previous[0]
        dy = nxt[1] - previous[1]
        length = math.hypot(dx, dy) or 1
        nx = -dy / length
        ny = dx / length
        output.append((point[0] + nx * offset, point[1] + ny * offset))
    return dedupe(output)


def kerf_coupon_pieces(path_d: str, width: float, height: float, kerf: float, samples_per_segment: int) -> List[List[Point]]:
    shared = sample_shared_cut(path_d, samples_per_segment)
    left_cut = offset_polyline(shared, -kerf / 2)
    right_cut = offset_polyline(shared, kerf / 2)

    left_piece = [(0, 0), left_cut[0], *left_cut[1:], (0, height)]
    right_piece = [right_cut[0], (width, 0), (width, height), right_cut[-1], *reversed(right_cut[1:-1])]
    return [ensure_ccw(dedupe(left_piece)), ensure_ccw(dedupe(right_piece))]


def scale_about_centroid(points: Sequence[Point], amount: float) -> List[Point]:
    if amount <= 0:
        return list(points)

    cx, cy = centroid(points)
    output = []
    for x, y in points:
        dx = x - cx
        dy = y - cy
        length = math.hypot(dx, dy)
        if length <= amount:
            output.append((x, y))
        else:
            output.append((x - dx / length * amount, y - dy / length * amount))
    return ensure_ccw(dedupe(output))


def shrink_polygon(points: Sequence[Point], amount: float) -> List[Point]:
    if amount <= 0:
        return list(points)

    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    shrunken = polygon.buffer(-amount, join_style="round", resolution=12)
    if shrunken.is_empty:
        raise ValueError("Shrink amount removed the whole polygon")
    if shrunken.geom_type == "MultiPolygon":
        shrunken = max(shrunken.geoms, key=lambda item: item.area)
    return ensure_ccw(dedupe([(float(x), float(y)) for x, y in shrunken.exterior.coords[:-1]]))


def round_plan_corners(points: Sequence[Point], radius: float) -> List[Point]:
    if radius <= 0:
        return list(points)

    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    rounded = polygon.buffer(-radius, join_style="round", resolution=12).buffer(
        radius, join_style="round", resolution=12
    )
    if rounded.is_empty:
        raise ValueError("Corner radius removed the whole polygon")
    if rounded.geom_type == "MultiPolygon":
        rounded = max(rounded.geoms, key=lambda item: item.area)
    return ensure_ccw(dedupe([(float(x), float(y)) for x, y in rounded.exterior.coords[:-1]]))


def translate_to_origin(points: Sequence[Point], margin: float = 0.0) -> List[Point]:
    min_x = min(x for x, _ in points)
    min_y = min(y for _, y in points)
    return [(x - min_x + margin, y - min_y + margin) for x, y in points]


def dedupe(points: Sequence[Point]) -> List[Point]:
    output: List[Point] = []
    for point in points:
        if not output or distance(output[-1], point) > 0.001:
            output.append(point)
    if len(output) > 1 and distance(output[0], output[-1]) < 0.001:
        output.pop()
    return output


def distance(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def signed_area(points: Sequence[Point]) -> float:
    area = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        area += point[0] * nxt[1] - nxt[0] * point[1]
    return area / 2


def ensure_ccw(points: List[Point]) -> List[Point]:
    return points if signed_area(points) > 0 else list(reversed(points))


def centroid(points: Sequence[Point]) -> Point:
    return (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points))


def triangulate_polygon(points: Sequence[Point]) -> List[Tuple[int, int, int]]:
    remaining = list(range(len(points)))
    triangles: List[Tuple[int, int, int]] = []
    guard = 0

    while len(remaining) > 3 and guard < len(points) * len(points):
        guard += 1
        clipped = False
        for cursor, current in enumerate(remaining):
            previous = remaining[cursor - 1]
            nxt = remaining[(cursor + 1) % len(remaining)]
            a, b, c = points[previous], points[current], points[nxt]

            if cross(a, b, c) <= 0:
                continue
            if any(
                point_in_triangle(points[other], a, b, c)
                for other in remaining
                if other not in (previous, current, nxt)
            ):
                continue

            triangles.append((previous, current, nxt))
            del remaining[cursor]
            clipped = True
            break

        if not clipped:
            raise ValueError("Could not triangulate pyjigsaw path")

    if len(remaining) == 3:
        triangles.append((remaining[0], remaining[1], remaining[2]))
    return triangles


def cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def point_in_triangle(point: Point, a: Point, b: Point, c: Point) -> bool:
    area = abs(cross(a, b, c))
    area_1 = abs(cross(point, a, b))
    area_2 = abs(cross(point, b, c))
    area_3 = abs(cross(point, c, a))
    return abs(area - (area_1 + area_2 + area_3)) < 0.0001


def extrude(points: Sequence[Point], thickness: float, bevel_height: float = 0.0, bevel_inset: float = 0.0) -> List[Triangle]:
    if bevel_height <= 0 or bevel_inset <= 0:
        return extrude_between(points, points, 0.0, thickness)

    bevel_height = min(bevel_height, thickness / 3)
    inset_points = scale_about_centroid(points, bevel_inset)
    triangles: List[Triangle] = []
    triangles.extend(cap(inset_points, 0.0, upward=False))
    triangles.extend(connect_layers(inset_points, points, 0.0, bevel_height))
    triangles.extend(connect_layers(points, points, bevel_height, thickness - bevel_height))
    triangles.extend(connect_layers(points, inset_points, thickness - bevel_height, thickness))
    triangles.extend(cap(inset_points, thickness, upward=True))
    return triangles


def extrude_between(bottom_points: Sequence[Point], top_points: Sequence[Point], z0: float, z1: float) -> List[Triangle]:
    if len(bottom_points) != len(top_points):
        raise ValueError("Bottom and top point counts must match")

    triangles: List[Triangle] = []
    triangles.extend(cap(bottom_points, z0, upward=False))
    triangles.extend(connect_layers(bottom_points, top_points, z0, z1))
    triangles.extend(cap(top_points, z1, upward=True))
    return triangles


def cap(points: Sequence[Point], z: float, upward: bool) -> List[Triangle]:
    triangles = []
    for a, b, c in triangulate_polygon(points):
        if upward:
            triangles.append((vertex(points[a], z), vertex(points[b], z), vertex(points[c], z)))
        else:
            triangles.append((vertex(points[c], z), vertex(points[b], z), vertex(points[a], z)))
    return triangles


def connect_layers(lower_points: Sequence[Point], upper_points: Sequence[Point], z0: float, z1: float) -> List[Triangle]:
    if len(lower_points) != len(upper_points):
        raise ValueError("Layer point counts must match")

    triangles = []
    for index, point in enumerate(lower_points):
        nxt = (index + 1) % len(lower_points)
        triangles.append((vertex(point, z0), vertex(lower_points[nxt], z0), vertex(upper_points[nxt], z1)))
        triangles.append((vertex(point, z0), vertex(upper_points[nxt], z1), vertex(upper_points[index], z1)))
    return triangles


def vertex(point: Point, z: float) -> Vertex:
    return (point[0], point[1], z)


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


def write_preview(path: Path, pieces: Sequence[Sequence[Point]]) -> None:
    colors = ["#196a60", "#b06b14", "#245b8f", "#7f4e91"]
    offset_x = 0.0
    paths = []
    for index, piece in enumerate(pieces):
        normalized = translate_to_origin(piece, 0)
        width = max(x for x, _ in normalized)
        command = " ".join(
            [f"M {normalized[0][0] + offset_x:.2f} {normalized[0][1]:.2f}"]
            + [f"L {x + offset_x:.2f} {y:.2f}" for x, y in normalized[1:]]
            + ["Z"]
        )
        paths.append(f'<path d="{command}" fill="{colors[index % len(colors)]}" stroke="#ffffff" stroke-width="0.25"/>')
        offset_x += width + 8

    height = max(max(y for _, y in piece) - min(y for _, y in piece) for piece in pieces)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 {offset_x + 1:.2f} {height + 2:.2f}" width="{offset_x:.2f}mm" height="{height:.2f}mm">
  <rect x="-1" y="-1" width="{offset_x + 1:.2f}" height="{height + 2:.2f}" fill="#f6f7f4"/>
  {"".join(paths)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate pyjigsaw-based STL coupons.")
    parser.add_argument("--out", default=None, help="Output directory")
    parser.add_argument("--width", type=float, default=52.0, help="Template width in mm")
    parser.add_argument("--height", type=float, default=24.0, help="Template height in mm")
    parser.add_argument("--rows", type=int, default=1)
    parser.add_argument("--cols", type=int, default=2)
    parser.add_argument("--thickness", type=float, default=3.0)
    parser.add_argument("--clearance", type=float, default=0.5, help="Kerf/cut-line width in mm")
    parser.add_argument("--chamfer", type=float, default=0.5, help="Backward-compatible alias for bevel height in mm")
    parser.add_argument("--bevel-height", type=float, default=None, help="Vertical height of bottom/top bevel bands in mm")
    parser.add_argument("--bevel-inset", type=float, default=0.25, help="Lateral inset for edge easing in mm")
    parser.add_argument("--samples", type=int, default=10, help="Samples per SVG segment")
    parser.add_argument("--seed", type=int, default=4)
    parser.add_argument("--mode", choices=["clean-shrink", "kerf"], default="clean-shrink")
    parser.add_argument("--shrink", type=float, default=0.1, help="True inward perimeter offset in mm for clean-shrink mode")
    parser.add_argument("--corner-radius", type=float, default=0.0, help="Top-down rounding radius for sharp plan corners in mm")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out or f"generated/pyjigsaw-coupons/0p{int(round(args.clearance * 100)):02d}")
    out.mkdir(parents=True, exist_ok=True)

    path_ds = build_cut_paths(args.width, args.height, args.rows, args.cols, args.seed)
    if args.mode == "kerf" and (args.rows != 1 or args.cols != 2):
        raise SystemExit("Kerf coupon mode currently supports only --rows 1 --cols 2")
    if args.mode == "kerf":
        raw_pieces = kerf_coupon_pieces(path_ds[0], args.width, args.height, args.clearance, args.samples)
    else:
        raw_pieces = [
            round_plan_corners(shrink_polygon(sample_svg_path(path_d, args.samples), args.shrink), args.corner_radius)
            for path_d in path_ds
        ]
    pieces = [translate_to_origin(piece, margin=0) for piece in raw_pieces]
    bevel_height = args.bevel_height if args.bevel_height is not None else args.chamfer

    for index, piece in enumerate(pieces, start=1):
        if args.mode == "kerf":
            name = f"pyjigsaw-0p{int(round(args.clearance * 100)):02d}-piece-{index:02d}"
        else:
            name = f"pyjigsaw-shrink-0p{int(round(args.shrink * 100)):02d}-piece-{index:02d}"
        write_ascii_stl(out / f"{name}.stl", name, extrude(piece, args.thickness, bevel_height, args.bevel_inset))

    (out / "template-paths.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">' + "".join(f'<path d="{d}" fill="none" stroke="black"/>' for d in path_ds) + "</svg>",
        encoding="utf-8",
    )
    write_preview(out / "preview.svg", pieces)
    print(f"Generated {len(pieces)} pyjigsaw coupon pieces in {out}")


if __name__ == "__main__":
    main()
