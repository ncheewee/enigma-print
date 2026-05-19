#!/usr/bin/env python3
"""Generate small separate jigsaw tolerance coupons."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

Point = Tuple[float, float]
Vertex = Tuple[float, float, float]
Triangle = Tuple[Vertex, Vertex, Vertex]


def edge_points(x: float, y0: float, y1: float, radius: float, direction: int, samples: int = 32) -> List[Point]:
    cy = (y0 + y1) / 2
    points: List[Point] = [(x, y0), (x, cy - radius)]
    for index in range(samples + 1):
        dy = -radius + 2 * radius * index / samples
        offset = math.sqrt(max(radius * radius - dy * dy, 0))
        points.append((x + direction * offset, cy + dy))
    points.extend([(x, cy + radius), (x, y1)])
    return dedupe(points)


def knob_piece(size: float, radius: float) -> List[Point]:
    x0 = 0
    x1 = size
    y0 = 0
    y1 = size
    points = [(x0, y0), (x1, y0)]
    points.extend(edge_points(x1, y0, y1, radius, 1)[1:])
    points.append((x0, y1))
    return dedupe(points)


def socket_piece(size: float, radius: float, clearance: float) -> List[Point]:
    x0 = 0
    x1 = size
    y0 = 0
    y1 = size
    points = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    edge = edge_points(x0, y1, y0, radius + clearance, 1)
    points.extend(edge[1:])
    return dedupe(points)


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


def extrude(points: Sequence[Point], thickness: float) -> List[Triangle]:
    triangles: List[Triangle] = []
    center = centroid(points)

    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        triangles.append((top(center, thickness), top(point, thickness), top(nxt, thickness)))
        triangles.append((bottom(center), bottom(nxt), bottom(point)))
        triangles.append((bottom(point), bottom(nxt), top(nxt, thickness)))
        triangles.append((bottom(point), top(nxt, thickness), top(point, thickness)))

    return triangles


def centroid(points: Sequence[Point]) -> Point:
    return (sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points))


def top(point: Point, z: float) -> Vertex:
    return (point[0], point[1], z)


def bottom(point: Point) -> Vertex:
    return (point[0], point[1], 0.0)


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


def write_svg(path: Path, knob: Sequence[Point], socket: Sequence[Point], size: float) -> None:
    def path_data(points: Sequence[Point], dx: float = 0) -> str:
        shifted = [(x + dx, y) for x, y in points]
        return " ".join([f"M {shifted[0][0]:.2f} {shifted[0][1]:.2f}", *[f"L {x:.2f} {y:.2f}" for x, y in shifted[1:]], "Z"])

    width = size * 2 + 8
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="-1 -1 {width + 2} {size + 2}" width="{width}mm" height="{size}mm">
  <rect x="-1" y="-1" width="{width + 2}" height="{size + 2}" fill="#f6f7f4"/>
  <path d="{path_data(knob)}" fill="#196a60" stroke="#ffffff" stroke-width="0.25"/>
  <path d="{path_data(socket, size + 8)}" fill="#b06b14" stroke="#ffffff" stroke-width="0.25"/>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate separate jigsaw fit coupons.")
    parser.add_argument("--out", default="generated/coupons/0p20", help="Output directory")
    parser.add_argument("--size", type=float, default=22.0, help="Coupon size in mm")
    parser.add_argument("--thickness", type=float, default=3.0, help="Coupon thickness in mm")
    parser.add_argument("--radius", type=float, default=4.2, help="Jigsaw knob radius in mm")
    parser.add_argument("--clearance", type=float, default=0.2, help="Socket radial clearance in mm")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    knob = knob_piece(args.size, args.radius)
    socket = socket_piece(args.size, args.radius, args.clearance)
    slug = f"jigsaw-0p{int(round(args.clearance * 100)):02d}"

    write_ascii_stl(out / f"{slug}-knob.stl", f"{slug}_knob", extrude(knob, args.thickness))
    write_ascii_stl(out / f"{slug}-socket.stl", f"{slug}_socket", extrude(socket, args.thickness))
    write_svg(out / f"{slug}-preview.svg", knob, socket, args.size)

    print(f"Generated separate 0.20 mm jigsaw coupons in {out}")
    print(f"Knob: {out / f'{slug}-knob.stl'}")
    print(f"Socket: {out / f'{slug}-socket.stl'}")


if __name__ == "__main__":
    main()
