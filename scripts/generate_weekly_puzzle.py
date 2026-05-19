#!/usr/bin/env python3
"""Generate the first Enigma Print MVP puzzle geometry.

This stage deliberately solves printability before art. It creates seven
interlocking, no-support STL pieces, a simple SVG preview, and a manifest that
the dashboard can later import or sync to Google Drive.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]
Segment = Tuple[Point, Point]
Triangle = Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[float, float, float]]


@dataclass
class Piece:
    day: int
    name: str
    left: str
    right: str
    polygon: List[Point]


def slugify(value: str) -> str:
    output = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            output.append(char)
            previous_dash = False
        elif not previous_dash:
            output.append("-")
            previous_dash = True
    return "".join(output).strip("-") or "weekly-puzzle"


def vertical_edge_points(
    x: float,
    y0: float,
    y1: float,
    feature: str,
    normal: int,
    tab_radius: float,
    samples: int,
) -> List[Point]:
    if feature == "flat":
        return [(x, y0), (x, y1)]

    cy = (y0 + y1) / 2
    radius = min(tab_radius, abs(y1 - y0) * 0.28)
    direction = 1 if y1 >= y0 else -1
    sign = normal if feature == "tab" else -normal
    points: List[Point] = [(x, y0), (x, cy - direction * radius)]

    for index in range(samples + 1):
        dy = -direction * radius + (2 * direction * radius * index / samples)
        offset = math.sqrt(max(radius * radius - dy * dy, 0))
        points.append((x + sign * offset, cy + dy))

    points.extend([(x, cy + direction * radius), (x, y1)])
    return dedupe_points(points)


def make_piece_polygon(
    index: int,
    count: int,
    board_width: float,
    board_height: float,
    gap: float,
    tab_radius: float,
    samples: int,
) -> Piece:
    piece_width = board_width / count
    x0 = index * piece_width + gap / 2
    x1 = (index + 1) * piece_width - gap / 2
    y0 = gap / 2
    y1 = board_height - gap / 2

    left_feature = "flat"
    right_feature = "flat"
    if index > 0:
        left_feature = "slot" if (index - 1) % 2 == 0 else "tab"
    if index < count - 1:
        right_feature = "tab" if index % 2 == 0 else "slot"

    points: List[Point] = []
    points.extend([(x0, y0), (x1, y0)])
    points.extend(vertical_edge_points(x1, y0, y1, right_feature, 1, tab_radius, samples)[1:])
    points.extend([(x0, y1)])
    points.extend(vertical_edge_points(x0, y1, y0, left_feature, -1, tab_radius, samples)[1:])

    polygon = ensure_ccw(dedupe_points(points))
    return Piece(
        day=index + 1,
        name=f"Day {index + 1} reveal",
        left=left_feature,
        right=right_feature,
        polygon=polygon,
    )


def dedupe_points(points: Sequence[Point]) -> List[Point]:
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
            raise ValueError("Could not triangulate puzzle piece outline")

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


def extrude_polygon(points: Sequence[Point], thickness: float) -> List[Triangle]:
    triangles_2d = triangulate_polygon(points)
    triangles: List[Triangle] = []

    for a, b, c in triangles_2d:
        triangles.append((top(points[a], thickness), top(points[b], thickness), top(points[c], thickness)))
        triangles.append((bottom(points[c]), bottom(points[b]), bottom(points[a])))

    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        triangles.append((bottom(point), bottom(nxt), top(nxt, thickness)))
        triangles.append((bottom(point), top(nxt, thickness), top(point, thickness)))

    return triangles


def point_in_polygon(point: Point, polygon: Sequence[Point]) -> bool:
    inside = False
    x, y = point
    previous = polygon[-1]
    for current in polygon:
        intersects = (current[1] > y) != (previous[1] > y)
        if intersects:
            slope_x = (previous[0] - current[0]) * (y - current[1]) / (previous[1] - current[1]) + current[0]
            if x < slope_x:
                inside = not inside
        previous = current
    return inside


def relief_segments(board_width: float, board_height: float, theme: str) -> List[Segment]:
    """Create a printable raised-line motif.

    The design is deterministic for now: an artifact-like medallion, orbit arcs,
    and botanical curves. Later this same interface can accept AI-derived vector
    paths or heightmap contours.
    """

    cx = board_width / 2
    cy = board_height / 2
    segments: List[Segment] = []

    segments.extend(polyline_segments(circle_points(cx, cy, min(board_height, board_width) * 0.24, 72)))
    segments.extend(polyline_segments(circle_points(cx, cy, min(board_height, board_width) * 0.14, 48)))

    for index in range(16):
        angle = 2 * math.pi * index / 16
        inner = min(board_height, board_width) * 0.25
        outer = inner + 4.0
        segments.append(
            (
                (cx + math.cos(angle) * inner, cy + math.sin(angle) * inner),
                (cx + math.cos(angle) * outer, cy + math.sin(angle) * outer),
            )
        )

    for lane in (0.28, 0.5, 0.72):
        points = []
        for step in range(96):
            t = step / 95
            x = 8 + t * (board_width - 16)
            y = board_height * lane + math.sin(t * math.pi * 2.5 + lane * 5) * 8
            points.append((x, y))
        segments.extend(polyline_segments(points))

    for x_factor in (0.18, 0.31, 0.57, 0.77, 0.88):
        x = board_width * x_factor
        y = board_height * (0.36 + 0.18 * math.sin(x_factor * 8))
        segments.extend(polyline_segments(ellipse_points(x, y, 5.4, 2.6, x_factor * math.pi, 18)))

    if theme == "artifact":
        for angle in (math.radians(35), math.radians(145), math.radians(215), math.radians(325)):
            length = min(board_height, board_width) * 0.36
            segments.append(
                (
                    (cx + math.cos(angle) * 6, cy + math.sin(angle) * 6),
                    (cx + math.cos(angle) * length, cy + math.sin(angle) * length),
                )
            )

    return segments


def circle_points(cx: float, cy: float, radius: float, samples: int) -> List[Point]:
    return [
        (cx + math.cos(2 * math.pi * index / samples) * radius, cy + math.sin(2 * math.pi * index / samples) * radius)
        for index in range(samples + 1)
    ]


def ellipse_points(cx: float, cy: float, rx: float, ry: float, rotation: float, samples: int) -> List[Point]:
    points = []
    for index in range(samples + 1):
        angle = 2 * math.pi * index / samples
        x = math.cos(angle) * rx
        y = math.sin(angle) * ry
        points.append(
            (
                cx + x * math.cos(rotation) - y * math.sin(rotation),
                cy + x * math.sin(rotation) + y * math.cos(rotation),
            )
        )
    return points


def polyline_segments(points: Sequence[Point]) -> List[Segment]:
    return [(points[index], points[index + 1]) for index in range(len(points) - 1)]


def relief_triangles_for_piece(
    polygon: Sequence[Point],
    segments: Sequence[Segment],
    base_z: float,
    relief_height: float,
    stroke_width: float,
) -> List[Triangle]:
    triangles: List[Triangle] = []
    step = max(stroke_width * 1.4, 1.2)

    for start, end in segments:
        length = distance(start, end)
        if length < 0.2:
            continue
        chunks = max(1, math.ceil(length / step))
        for index in range(chunks):
            t0 = index / chunks
            t1 = (index + 1) / chunks
            p0 = lerp(start, end, t0)
            p1 = lerp(start, end, t1)
            mid = lerp(p0, p1, 0.5)
            if point_in_polygon(mid, polygon):
                triangles.extend(stroke_prism(p0, p1, base_z, relief_height, stroke_width))

    return triangles


def lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def stroke_prism(start: Point, end: Point, base_z: float, relief_height: float, width: float) -> List[Triangle]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 0.001:
        return []

    nx = -dy / length * width / 2
    ny = dx / length * width / 2
    cap = width * 0.2
    ux = dx / length * cap
    uy = dy / length * cap
    base = [
        (start[0] - ux + nx, start[1] - uy + ny),
        (end[0] + ux + nx, end[1] + uy + ny),
        (end[0] + ux - nx, end[1] + uy - ny),
        (start[0] - ux - nx, start[1] - uy - ny),
    ]
    return extrude_between_z(base, base_z, base_z + relief_height)


def extrude_between_z(points: Sequence[Point], z0: float, z1: float) -> List[Triangle]:
    top_vertices = [(x, y, z1) for x, y in points]
    bottom_vertices = [(x, y, z0) for x, y in points]
    triangles: List[Triangle] = [
        (top_vertices[0], top_vertices[1], top_vertices[2]),
        (top_vertices[0], top_vertices[2], top_vertices[3]),
    ]
    for index in range(len(points)):
        nxt = (index + 1) % len(points)
        triangles.append((bottom_vertices[index], bottom_vertices[nxt], top_vertices[nxt]))
        triangles.append((bottom_vertices[index], top_vertices[nxt], top_vertices[index]))
    return triangles


def top(point: Point, thickness: float) -> Tuple[float, float, float]:
    return (point[0], point[1], thickness)


def bottom(point: Point) -> Tuple[float, float, float]:
    return (point[0], point[1], 0.0)


def write_ascii_stl(path: Path, name: str, triangles: Iterable[Triangle]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"solid {name}\n")
        for tri in triangles:
            normal = triangle_normal(tri)
            handle.write(f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n")
            handle.write("    outer loop\n")
            for vertex in tri:
                handle.write(f"      vertex {vertex[0]:.4f} {vertex[1]:.4f} {vertex[2]:.4f}\n")
            handle.write("    endloop\n")
            handle.write("  endfacet\n")
        handle.write(f"endsolid {name}\n")


def triangle_normal(triangle: Triangle) -> Tuple[float, float, float]:
    a, b, c = triangle
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
    return (nx / length, ny / length, nz / length)


def write_preview_svg(
    path: Path,
    pieces: Sequence[Piece],
    board_width: float,
    board_height: float,
    segments: Sequence[Segment],
) -> None:
    colors = ["#196a60", "#b06b14", "#245b8f", "#7f4e91", "#4f7d2b", "#9b3d3d", "#4d6f86"]
    paths = []
    for index, piece in enumerate(pieces):
        commands = [f"M {piece.polygon[0][0]:.2f} {piece.polygon[0][1]:.2f}"]
        commands.extend(f"L {x:.2f} {y:.2f}" for x, y in piece.polygon[1:])
        commands.append("Z")
        center = polygon_centroid(piece.polygon)
        paths.append(
            f'<path d="{" ".join(commands)}" fill="{colors[index % len(colors)]}" '
            'stroke="#f6f7f4" stroke-width="0.9"/>'
        )
        paths.append(
            f'<text x="{center[0]:.2f}" y="{center[1]:.2f}" fill="#ffffff" '
            'font-size="8" font-family="Arial, sans-serif" text-anchor="middle" '
            'dominant-baseline="middle" font-weight="700">'
            f"{piece.day}</text>"
        )

    relief = []
    for start, end in segments:
        relief.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" x2="{end[0]:.2f}" y2="{end[1]:.2f}" '
            'stroke="rgba(255,255,255,0.7)" stroke-width="1.1" stroke-linecap="round"/>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {board_width} {board_height}" width="{board_width}mm" height="{board_height}mm">
  <rect width="{board_width}" height="{board_height}" fill="#f6f7f4"/>
  {"".join(paths)}
  {"".join(relief)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_source_svg(path: Path, board_width: float, board_height: float, segments: Sequence[Segment]) -> None:
    relief = []
    for start, end in segments:
        relief.append(
            f'<line x1="{start[0]:.2f}" y1="{start[1]:.2f}" x2="{end[0]:.2f}" y2="{end[1]:.2f}" '
            'stroke="#f8f4df" stroke-width="1.3" stroke-linecap="round"/>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {board_width} {board_height}" width="{board_width}mm" height="{board_height}mm">
  <rect width="{board_width}" height="{board_height}" fill="#173f3a"/>
  <rect x="4" y="4" width="{board_width - 8}" height="{board_height - 8}" rx="3" fill="none" stroke="#d1a24d" stroke-width="1"/>
  {"".join(relief)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def polygon_centroid(points: Sequence[Point]) -> Point:
    area = signed_area(points)
    if abs(area) < 0.001:
        return (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points))
    cx = 0.0
    cy = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        factor = point[0] * nxt[1] - nxt[0] * point[1]
        cx += (point[0] + nxt[0]) * factor
        cy += (point[1] + nxt[1]) * factor
    return (cx / (6 * area), cy / (6 * area))


def build_manifest(
    name: str,
    slug: str,
    pieces: Sequence[Piece],
    start_date: date,
    board_width: float,
    board_height: float,
    thickness: float,
    relief_height: float,
    relief_theme: str,
) -> dict:
    now = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    project_path = f"generated/{slug}"
    return {
        "id": slug,
        "name": name,
        "slug": slug,
        "status": "generated",
        "summary": "Raised-relief MVP puzzle: seven interlocking STL pieces with a printable artifact motif.",
        "targetPrinter": "A1 mini",
        "createdAt": now,
        "updatedAt": now,
        "generator": {
            "version": 1,
            "mode": "raised-relief",
            "reliefTheme": relief_theme,
            "boardWidthMm": board_width,
            "boardHeightMm": board_height,
            "thicknessMm": thickness,
            "reliefHeightMm": relief_height,
            "pieceCount": len(pieces),
        },
        "assets": {
            "preview": f"{project_path}/preview.svg",
            "sourceHidden": f"{project_path}/source-hidden.svg",
            "manifest": f"{project_path}/manifest.json",
        },
        "files": [
            {"name": "manifest.json", "type": "JSON", "description": "Project metadata"},
            {"name": "preview.svg", "type": "SVG", "description": "Top-down piece layout preview"},
            {"name": "source-hidden.svg", "type": "SVG", "description": "Clean final reveal artwork"},
        ],
        "pieces": [
            {
                "id": f"{slug}-{piece.day}",
                "day": piece.day,
                "name": piece.name,
                "filename": f"{slug}-day-{piece.day:02d}.stl",
                "scheduledFor": (start_date + timedelta(days=piece.day - 1)).isoformat(),
                "status": "pending",
                "printedAt": None,
                "note": f"Raised-relief piece with {piece.left} left edge and {piece.right} right edge.",
            }
            for piece in pieces
        ],
    }


def write_generated_index(root: Path) -> None:
    projects = []
    for manifest_path in sorted(root.glob("*/manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            projects.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue

    (root / "index.json").write_text(json.dumps({"projects": projects}, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Enigma Print weekly puzzle STL files.")
    parser.add_argument("--name", default="Week 1: Geometry Fit Test", help="Project display name")
    parser.add_argument("--slug", default=None, help="Project slug. Defaults to slugified name")
    parser.add_argument("--out", default="generated", help="Output directory")
    parser.add_argument("--start-date", default=date.today().isoformat(), help="First scheduled print date")
    parser.add_argument("--pieces", type=int, default=7, help="Number of daily pieces")
    parser.add_argument("--width", type=float, default=140.0, help="Completed puzzle width in mm")
    parser.add_argument("--height", type=float, default=84.0, help="Completed puzzle height in mm")
    parser.add_argument("--thickness", type=float, default=4.0, help="Piece thickness in mm")
    parser.add_argument("--relief-height", type=float, default=0.8, help="Raised relief height in mm")
    parser.add_argument("--stroke-width", type=float, default=1.1, help="Raised relief stroke width in mm")
    parser.add_argument("--relief-theme", default="artifact", choices=["artifact", "garden"], help="Relief motif")
    parser.add_argument("--gap", type=float, default=0.35, help="Assembly/printing clearance in mm")
    parser.add_argument("--tab-radius", type=float, default=5.5, help="Interlock tab radius in mm")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.pieces < 2:
        raise SystemExit("--pieces must be at least 2")

    slug = args.slug or slugify(args.name)
    output_dir = Path(args.out) / slug
    output_dir.mkdir(parents=True, exist_ok=True)

    start_date = date.fromisoformat(args.start_date)
    pieces = [
        make_piece_polygon(index, args.pieces, args.width, args.height, args.gap, args.tab_radius, 18)
        for index in range(args.pieces)
    ]
    segments = relief_segments(args.width, args.height, args.relief_theme)

    for piece in pieces:
        triangles = extrude_polygon(piece.polygon, args.thickness)
        triangles.extend(
            relief_triangles_for_piece(piece.polygon, segments, args.thickness, args.relief_height, args.stroke_width)
        )
        write_ascii_stl(output_dir / f"{slug}-day-{piece.day:02d}.stl", f"{slug}_day_{piece.day:02d}", triangles)

    write_preview_svg(output_dir / "preview.svg", pieces, args.width, args.height, segments)
    write_source_svg(output_dir / "source-hidden.svg", args.width, args.height, segments)
    manifest = build_manifest(
        args.name,
        slug,
        pieces,
        start_date,
        args.width,
        args.height,
        args.thickness,
        args.relief_height,
        args.relief_theme,
    )
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_generated_index(Path(args.out))

    print(f"Generated {len(pieces)} STL pieces in {output_dir}")
    print(f"Preview: {output_dir / 'preview.svg'}")
    print(f"Manifest: {output_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
