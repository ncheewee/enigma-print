#!/usr/bin/env python3
"""Generate a small four-piece, two-colour surprise jigsaw puzzle."""

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
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from PIL import Image, ImageDraw
from pyjigsaw import jigsawfactory
from shapely.affinity import rotate
from shapely.geometry import LineString, Point as ShapelyPoint, Polygon
from shapely.ops import triangulate, unary_union
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


def relic_island_art(width: float, height: float) -> List[Polygon]:
    """A set of small relic marks, kept inside quadrants for clean clipping."""
    shapes: List[Polygon] = []
    shapes.append(ShapelyPoint(width * 0.28, height * 0.72).buffer(3.0, resolution=24))
    shapes.append(star_polygon(width * 0.72, height * 0.72, 2.4, 1.0))
    shapes.append(
        Polygon(
            [
                (width * 0.18, height * 0.20),
                (width * 0.30, height * 0.40),
                (width * 0.42, height * 0.20),
            ]
        ).buffer(0.25, join_style="round")
    )
    shapes.append(
        Polygon(
            [
                (width * 0.72, height * 0.14),
                (width * 0.84, height * 0.26),
                (width * 0.72, height * 0.38),
                (width * 0.60, height * 0.26),
            ]
        ).buffer(0.25, join_style="round")
    )
    return shapes


def orbit_shrine_art(width: float, height: float) -> List[Polygon]:
    """A different chunky motif for confirming the irregular workflow."""
    shapes: List[Polygon] = []
    shapes.append(Polygon([(width * 0.14, height * 0.72), (width * 0.28, height * 0.84), (width * 0.42, height * 0.72), (width * 0.28, height * 0.60)]).buffer(0.25, join_style="round"))
    shapes.append(ShapelyPoint(width * 0.72, height * 0.74).buffer(3.0, resolution=24))
    shapes.append(LineString([(width * 0.61, height * 0.74), (width * 0.83, height * 0.74)]).buffer(0.75, cap_style="round"))
    shapes.append(LineString([(width * 0.72, height * 0.63), (width * 0.72, height * 0.85)]).buffer(0.75, cap_style="round"))
    shapes.append(Polygon([(width * 0.18, height * 0.16), (width * 0.36, height * 0.16), (width * 0.27, height * 0.34)]).buffer(0.25, join_style="round"))
    shapes.append(star_polygon(width * 0.70, height * 0.24, 2.6, 1.1))
    shapes.append(LineString([(width * 0.58, height * 0.16), (width * 0.84, height * 0.32)]).buffer(0.65, cap_style="round"))
    return shapes


def surprise_art(width: float, height: float, design: str) -> List[Polygon]:
    if design == "orbit-shrine":
        return orbit_shrine_art(width, height)
    return relic_island_art(width, height)


def irregular_silhouette(width: float, height: float, variant: str = "relic") -> Polygon:
    """A rounded relic-like outer boundary that still keeps four printable pieces."""
    cx = width / 2
    cy = height / 2
    points = []
    for index in range(28):
        angle = 2 * math.pi * index / 28
        if variant == "orbit-shrine":
            wobble = 1 + 0.10 * math.sin(angle * 4 - 0.2) + 0.09 * math.cos(angle * 6 + 0.9)
            rx = width * 0.43 * wobble
            ry = height * 0.44 * (1 + 0.08 * math.cos(angle * 3 - 0.8) - 0.05 * math.sin(angle * 5))
        else:
            wobble = 1 + 0.12 * math.sin(angle * 3 + 0.7) + 0.08 * math.cos(angle * 5 - 0.4)
            rx = width * 0.45 * wobble
            ry = height * 0.42 * (1 + 0.10 * math.cos(angle * 2 + 1.3) - 0.06 * math.sin(angle * 4))
        x = cx + math.cos(angle) * rx
        y = cy + math.sin(angle) * ry
        points.append((x, y))
    return Polygon(points).buffer(0.8, join_style="round", resolution=12).buffer(
        -0.8, join_style="round", resolution=12
    )


def star_polygon(cx: float, cy: float, outer: float, inner: float) -> Polygon:
    points = []
    for index in range(10):
        angle = math.radians(-90 + index * 36)
        radius = outer if index % 2 == 0 else inner
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))
    return Polygon(points).buffer(0)


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
                top = (vertex(coords[0], z1), vertex(coords[index], z1), vertex(coords[index + 1], z1))
                bottom = (vertex(coords[index + 1], z0), vertex(coords[index], z0), vertex(coords[0], z0))
                if triangle_area(top) > 0.000001:
                    triangles.append(top)
                    triangles.append(bottom)

    rings = [list(polygon.exterior.coords[:-1]), *[list(ring.coords[:-1]) for ring in polygon.interiors]]
    for ring in rings:
        for index, point in enumerate(ring):
            nxt = ring[(index + 1) % len(ring)]
            triangles.append((vertex(point, z0), vertex(nxt, z0), vertex(nxt, z1)))
            triangles.append((vertex(point, z0), vertex(nxt, z1), vertex(point, z1)))
    return triangles


def extrude_exact_polygon(polygon: Polygon, z0: float, z1: float) -> List[Triangle]:
    """Extrude a simple polygon using one exact outline for caps and walls."""
    if polygon.geom_type != "Polygon" or polygon.area <= 0:
        return []
    if polygon.interiors:
        return extrude_polygon(polygon, z0, z1)

    outline = ensure_ccw(dedupe([(float(x), float(y)) for x, y in polygon.exterior.coords[:-1]]))
    if len(outline) < 3:
        return []

    triangles: List[Triangle] = []
    triangles.extend(cap(outline, z0, upward=False))
    triangles.extend(connect_layers(outline, outline, z0, z1))
    triangles.extend(cap(outline, z1, upward=True))
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


def extrude_piece_safe_bevel(polygon: Polygon, thickness: float, bevel_height: float, bevel_inset: float) -> List[Triangle]:
    """Bottom-only inward bevel for elephant-foot relief; top remains true outline."""
    if bevel_height <= 0 or bevel_inset <= 0:
        return extrude_polygon(polygon, 0, thickness)

    bevel_height = min(bevel_height, thickness / 3)
    inset_polygon = polygon.buffer(-bevel_inset, join_style="round", resolution=8)
    if inset_polygon.is_empty:
        return extrude_polygon(polygon, 0, thickness)
    if inset_polygon.geom_type == "MultiPolygon":
        inset_polygon = max(inset_polygon.geoms, key=lambda item: item.area)

    sample_count = max(180, int(max(polygon.exterior.length, inset_polygon.exterior.length) / 0.28))
    outline = resample_exterior(polygon, sample_count)
    inset = resample_exterior(inset_polygon, sample_count)

    triangles: List[Triangle] = []
    triangles.extend(cap(inset, 0, upward=False))
    triangles.extend(connect_layers(inset, outline, 0, bevel_height))
    triangles.extend(connect_layers(outline, outline, bevel_height, thickness))
    triangles.extend(cap(outline, thickness, upward=True))
    return triangles


def extrude_piece_radial_bottom_bevel(
    polygon: Polygon, thickness: float, bevel_height: float, bevel_inset: float
) -> List[Triangle]:
    """Slicer-friendly top/bottom bevel using identical vertex counts/order."""
    if bevel_height <= 0 or bevel_inset <= 0:
        return extrude_polygon(polygon, 0, thickness)

    simplified = polygon.simplify(0.04, preserve_topology=True)
    outline = ensure_ccw(dedupe([(float(x), float(y)) for x, y in simplified.exterior.coords[:-1]]))
    center = polygon.representative_point()
    inset_outline: List[Point] = []
    for x, y in outline:
        dx = float(center.x) - x
        dy = float(center.y) - y
        length = math.hypot(dx, dy)
        if length <= bevel_inset:
            inset_outline.append((x, y))
        else:
            inset_outline.append((x + dx / length * bevel_inset, y + dy / length * bevel_inset))

    inset_polygon = Polygon(inset_outline)
    if not inset_polygon.is_valid or inset_polygon.is_empty:
        return extrude_polygon(polygon, 0, thickness)

    bevel_height = min(bevel_height, thickness / 3)
    triangles: List[Triangle] = []
    triangles.extend(cap(inset_outline, 0, upward=False))
    triangles.extend(connect_layers(inset_outline, outline, 0, bevel_height))
    triangles.extend(connect_layers(outline, outline, bevel_height, thickness - bevel_height))
    triangles.extend(connect_layers(outline, inset_outline, thickness - bevel_height, thickness))
    triangles.extend(cap(inset_outline, thickness, upward=True))
    return triangles


def resample_exterior(polygon: Polygon, count: int) -> List[Point]:
    ring = polygon.exterior
    points = []
    for index in range(count):
        point = ring.interpolate(ring.length * index / count)
        points.append((float(point.x), float(point.y)))
    return ensure_ccw(dedupe(points))


def cap(points: Sequence[Point], z: float, upward: bool) -> List[Triangle]:
    triangles: List[Triangle] = []
    for a, b, c in triangulate_points(points):
        if upward:
            triangles.append((vertex(points[a], z), vertex(points[b], z), vertex(points[c], z)))
        else:
            triangles.append((vertex(points[c], z), vertex(points[b], z), vertex(points[a], z)))
    return triangles


def triangulate_points(points: Sequence[Point]) -> List[Tuple[int, int, int]]:
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
            polygon = Polygon(points)
            for tri in triangulate(polygon):
                clipped_poly = tri.intersection(polygon)
                if clipped_poly.is_empty or clipped_poly.geom_type != "Polygon":
                    continue
                coords = list(clipped_poly.exterior.coords[:-1])
                base = len(points)
                # Fallback should be rare; callers using side walls should avoid it.
                del base
            raise ValueError("Could not triangulate cap with exact vertices")

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


def connect_layers(lower: Sequence[Point], upper: Sequence[Point], z0: float, z1: float) -> List[Triangle]:
    triangles: List[Triangle] = []
    for index, point in enumerate(lower):
        nxt = (index + 1) % len(lower)
        triangles.append((vertex(point, z0), vertex(lower[nxt], z0), vertex(upper[nxt], z1)))
        triangles.append((vertex(point, z0), vertex(upper[nxt], z1), vertex(upper[index], z1)))
    return triangles


def write_3mf(
    path: Path,
    base_triangles: Sequence[Triangle],
    art_triangles: Sequence[Triangle],
    width: float,
    height: float,
    total_height: float,
) -> None:
    model_xml = build_model_xml(base_triangles, art_triangles)
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types_xml)
        package.writestr("_rels/.rels", rels_xml)
        package.writestr("3D/3dmodel.model", model_xml)
        package.writestr(
            "Metadata/model_settings.config",
            bambu_model_settings_xml(path.name, len(base_triangles), len(art_triangles)),
        )


def write_bambu_project_3mf(
    path: Path,
    base_triangles: Sequence[Triangle],
    art_triangles: Sequence[Triangle],
    width: float,
    height: float,
    total_height: float,
) -> None:
    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>
 <Relationship Target="/Metadata/plate_1_small.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>
</Relationships>
"""
    content_types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="config" ContentType="application/octet-stream"/>
</Types>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types_xml)
        package.writestr("_rels/.rels", rels_xml)
        package.writestr("3D/3dmodel.model", bambu_single_model_xml(base_triangles, art_triangles, width, height))
        package.writestr(
            "Metadata/model_settings.config",
            bambu_part_model_settings_xml(path.name, len(base_triangles), len(art_triangles)),
        )
        package.writestr("Metadata/project_settings.config", bambu_project_settings_json())
        package.writestr("Metadata/filament_sequence.json", '{"plate_1":{"nozzle_sequence":[],"optimal_assignment":[],"sequence":[]}}')
        package.writestr(
            "Metadata/slice_info.config",
            """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.06.00.51"/>
  </header>
</config>
""",
        )
        package.writestr(
            "Metadata/cut_information.xml",
            """<?xml version="1.0" encoding="utf-8"?>
<objects>
 <object id="1">
  <cut_id id="0" check_sum="1" connectors_cnt="0"/>
 </object>
</objects>
""",
        )
        copy_reference_thumbnails(package)


def build_model_xml(base_triangles: Sequence[Triangle], art_triangles: Sequence[Triangle]) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <metadata name="Application">Enigma Print</metadata>
  <metadata name="Title">Enigma Print two-filament puzzle piece</metadata>
  <resources>
    <basematerials id="1">
      <base name="Base colour" displaycolor="#163D3AFF"/>
      <base name="Reveal colour" displaycolor="#F7E8A4FF"/>
    </basematerials>
    {object_xml(1, "base_colour_1", base_triangles, 0)}
    {object_xml(2, "reveal_colour_2", art_triangles, 1)}
  </resources>
  <build>
    <item objectid="1"/>
    <item objectid="2"/>
  </build>
</model>
"""


def bambu_model_settings_xml(source_file: str, base_faces: int, art_faces: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="1">
    <metadata key="name" value="base_colour_1"/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{base_faces}"/>
    <metadata key="source_file" value="{source_file}"/>
    <metadata key="source_object_id" value="1"/>
    <metadata key="source_volume_id" value="0"/>
    <mesh_stat face_count="{base_faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
  </object>
  <object id="2">
    <metadata key="name" value="reveal_colour_2"/>
    <metadata key="extruder" value="2"/>
    <metadata face_count="{art_faces}"/>
    <metadata key="source_file" value="{source_file}"/>
    <metadata key="source_object_id" value="2"/>
    <metadata key="source_volume_id" value="1"/>
    <mesh_stat face_count="{art_faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1 2"/>
    <metadata key="filament_volume_maps" value="0 0"/>
    <model_instance>
      <metadata key="object_id" value="1"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="101"/>
    </model_instance>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="102"/>
    </model_instance>
  </plate>
</config>
"""


def bambu_single_model_xml(
    base_triangles: Sequence[Triangle], art_triangles: Sequence[Triangle], width: float, height: float
) -> str:
    base_object = bambu_inline_object_xml(1, base_triangles)
    art_object = bambu_inline_object_xml(2, art_triangles)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">
  <metadata name="Application">BambuStudio-02.06.00.51</metadata>
  <metadata name="BambuStudio:3mfVersion">1</metadata>
  <metadata name="CreationDate">{datetime.now().date().isoformat()}</metadata>
  <metadata name="ModificationDate">{datetime.now().date().isoformat()}</metadata>
  <metadata name="Title">Enigma Print puzzle piece</metadata>
  <resources>
{base_object}
{art_object}
    <object id="3" type="model" name="enigma_print_piece">
      <components>
        <component objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
        <component objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
      </components>
    </object>
  </resources>
  <build>
    <item objectid="3" transform="1 0 0 0 1 0 0 0 1 {90 - width / 2:.5f} {90 - height / 2:.5f} 0" printable="1"/>
  </build>
</model>
"""


def bambu_inline_object_xml(object_id: int, triangles: Sequence[Triangle]) -> str:
    vertices, triangle_indices = indexed_mesh(triangles)
    vertices_xml = "\n".join(f'        <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in vertices)
    triangles_xml = "\n".join(f'        <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangle_indices)
    return f"""    <object id="{object_id}" type="model">
      <mesh>
        <vertices>
{vertices_xml}
        </vertices>
        <triangles>
{triangles_xml}
        </triangles>
      </mesh>
    </object>"""


def bambu_root_model_xml(width: float, height: float, total_height: float) -> str:
    del total_height
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
  <metadata name="Application">BambuStudio-02.06.00.51</metadata>
  <metadata name="BambuStudio:3mfVersion">1</metadata>
  <metadata name="CreationDate">{datetime.now().date().isoformat()}</metadata>
  <metadata name="Title">Enigma Print puzzle piece</metadata>
  <resources>
    <object id="2" p:UUID="00000002-61cb-4c03-9d28-80fed5dfa1dc" type="model" name="enigma_print_piece">
      <components>
        <component p:path="/3D/Objects/object_1.model" objectid="1" p:UUID="00000001-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
        <component p:path="/3D/Objects/object_3.model" objectid="3" p:UUID="00000003-b206-40ff-9872-83e8017abed1" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>
      </components>
    </object>
  </resources>
  <build p:UUID="2c7c17d8-22b5-4d84-8835-1976022ea369">
    <item objectid="2" p:UUID="00000002-b1ec-4553-aec9-835e5b724bb4" transform="1 0 0 0 1 0 0 0 1 {90 - width / 2:.5f} {90 - height / 2:.5f} 0" printable="1"/>
  </build>
</model>
"""


def bambu_mesh_model_xml(object_id: int, name: str, triangles: Sequence[Triangle]) -> str:
    vertices, triangle_indices = indexed_mesh(triangles)
    vertices_xml = "\n".join(f'        <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in vertices)
    triangles_xml = "\n".join(f'        <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangle_indices)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
  <metadata name="BambuStudio:3mfVersion">1</metadata>
  <resources>
    <object id="{object_id}" p:UUID="0000000{object_id}-81cb-4c03-9d28-80fed5dfa1dc" type="model" name="{name}">
      <mesh>
        <vertices>
{vertices_xml}
        </vertices>
        <triangles>
{triangles_xml}
        </triangles>
      </mesh>
    </object>
  </resources>
  <build/>
</model>
"""


def bambu_part_model_settings_xml(source_file: str, base_faces: int, art_faces: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="3">
    <metadata key="name" value="enigma_print_piece"/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{base_faces + art_faces}"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="base_colour_1"/>
      <metadata key="extruder" value="1"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="{source_file}"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="0"/>
      <mesh_stat face_count="{base_faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
    <part id="2" subtype="normal_part">
      <metadata key="name" value="reveal_colour_2"/>
      <metadata key="extruder" value="2"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="{source_file}"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="1"/>
      <mesh_stat face_count="{art_faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
  </object>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1 2"/>
    <metadata key="filament_volume_maps" value="0 0"/>
    <model_instance>
      <metadata key="object_id" value="3"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="901"/>
    </model_instance>
  </plate>
  <assemble>
    <assemble_item object_id="3" instance_id="0" transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0" />
  </assemble>
</config>
"""


def bambu_project_settings_json() -> str:
    template = Path("reference-bambu-filament2.3mf")
    if not template.exists():
        template = Path("generated/logo/multicolor-single-piece-diagnostic/enigma-block-mark-bambu-project.3mf")
    settings = {}
    if template.exists():
        with zipfile.ZipFile(template) as package:
            settings = json.loads(package.read("Metadata/project_settings.config"))
    if settings:
        settings["filament_colour"] = ["#163D3A", "#F7E8A4"]
    else:
        settings = {
            "filament_colour": ["#163D3A", "#F7E8A4"],
            "filament_type": ["PLA", "PLA"],
            "filament_settings_id": ["Bambu PLA Basic 200C", "Bambu PLA Basic 200C"],
            "filament_ids": ["GFA00", "GFA00"],
            "filament_map": ["1", "1"],
            "filament_colour_type": ["1", "1"],
            "has_filament_switcher": "0",
            "single_extruder_multi_material": "1",
            "printer_model": "Bambu Lab A1 mini",
        }
    return json.dumps(settings, indent=4)


def copy_reference_thumbnails(package: zipfile.ZipFile) -> None:
    template = Path("reference-bambu-filament2.3mf")
    if not template.exists():
        return
    with zipfile.ZipFile(template) as reference:
        for name in [
            "Metadata/plate_1.png",
            "Metadata/plate_1_small.png",
            "Metadata/plate_no_light_1.png",
            "Metadata/top_1.png",
            "Metadata/pick_1.png",
        ]:
            if name in reference.namelist():
                package.writestr(name, reference.read(name))


def centered(triangles: Iterable[Triangle], width: float, height: float) -> List[Triangle]:
    return [
        tuple((x - width / 2, y - height / 2, z) for x, y, z in triangle)  # type: ignore[misc]
        for triangle in triangles
    ]


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


def nonmanifold_edges(triangles: Sequence[Triangle]) -> int:
    _, triangle_indices = indexed_mesh(triangles)
    edges: Counter[Tuple[int, int]] = Counter()
    for a, b, c in triangle_indices:
        for edge in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted(edge))] += 1
    return sum(1 for count in edges.values() if count != 2)


def write_preview(
    path: Path,
    pieces: Sequence[Polygon],
    art: Sequence[Polygon],
    width: float,
    height: float,
    silhouette: Polygon | None = None,
) -> None:
    scale = 10
    image = Image.new("RGB", (int(width * scale), int(height * scale)), "#163d3a")
    draw = ImageDraw.Draw(image)
    for polygon in art:
        parts = list(polygon.geoms) if polygon.geom_type == "MultiPolygon" else [polygon]
        for part in parts:
            if part.geom_type != "Polygon":
                continue
            coords = [(x * scale, (height - y) * scale) for x, y in part.exterior.coords]
            draw.polygon(coords, fill="#f7e8a4")
    for polygon in pieces:
        coords = [(x * scale, (height - y) * scale) for x, y in polygon.exterior.coords]
        draw.line(coords, fill="#d1a24d", width=2, joint="curve")
    if silhouette is not None:
        coords = [(x * scale, (height - y) * scale) for x, y in silhouette.exterior.coords]
        draw.line(coords, fill="#f7e8a4", width=3, joint="curve")
    image.save(path)


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a 4-piece surprise multicolour jigsaw.")
    parser.add_argument("--out", default="generated/surprises/relic-island-4pc-v2")
    parser.add_argument("--width", type=float, default=50.0)
    parser.add_argument("--height", type=float, default=50.0)
    parser.add_argument("--name", default="Relic Island")
    parser.add_argument("--design", choices=["relic-island", "orbit-shrine"], default="relic-island")
    parser.add_argument("--format", choices=["generic", "bambu-project"], default="bambu-project")
    parser.add_argument("--irregular", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--cols", type=int, default=2)
    parser.add_argument("--base-thickness", type=float, default=2.4)
    parser.add_argument("--art-height", type=float, default=1.2)
    parser.add_argument("--art-embed", type=float, default=0.08)
    parser.add_argument("--shrink", type=float, default=0.10)
    parser.add_argument("--corner-radius", type=float, default=0.50)
    parser.add_argument("--bevel-height", type=float, default=0.50)
    parser.add_argument("--bevel-inset", type=float, default=0.25)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--seed", type=int, default=11)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    pieces = [
        clean_piece_polygon(sample_svg_path(path_d, args.samples), args.shrink, args.corner_radius)
        for path_d in build_cut_paths(args.width, args.height, args.rows, args.cols, args.seed)
    ]
    silhouette = irregular_silhouette(args.width, args.height, args.design) if args.irregular else None
    if silhouette is not None:
        clipped_pieces: List[Polygon] = []
        for piece in pieces:
            clipped = piece.intersection(silhouette)
            if clipped.is_empty:
                continue
            if clipped.geom_type == "MultiPolygon":
                clipped = max(clipped.geoms, key=lambda item: item.area)
            if clipped.geom_type == "Polygon" and clipped.area > 0:
                clipped_pieces.append(clipped)
        pieces = clipped_pieces

    merged_art = unary_union(surprise_art(args.width, args.height, args.design))
    art = list(merged_art.geoms) if merged_art.geom_type == "MultiPolygon" else [merged_art]
    write_preview(out / "preview.png", pieces, art, args.width, args.height, silhouette)

    piece_entries = []
    for index, piece in enumerate(pieces, start=1):
        if args.irregular:
            base_triangles = extrude_piece_radial_bottom_bevel(
                piece, args.base_thickness, args.bevel_height, args.bevel_inset
            )
        else:
            base_triangles = extrude_piece(piece, args.base_thickness, args.bevel_height, args.bevel_inset)
        art_triangles: List[Triangle] = []
        reveal_clip = piece.buffer(-0.08, join_style="round", resolution=8)
        for shape in art:
            clipped = shape.intersection(reveal_clip)
            if clipped.is_empty:
                continue
            if clipped.geom_type == "GeometryCollection":
                parts = [part for part in clipped.geoms if part.geom_type == "Polygon"]
            else:
                parts = list(clipped.geoms) if clipped.geom_type == "MultiPolygon" else [clipped]
            for part in parts:
                if part.geom_type == "Polygon" and part.area > 0.4:
                    part = part.buffer(0)
                    art_triangles.extend(
                        extrude_exact_polygon(
                            part, args.base_thickness - args.art_embed, args.base_thickness + args.art_height
                        )
                    )

        filename = f"piece-{index:02d}.3mf"
        if args.format == "bambu-project":
            write_bambu_project_3mf(
                out / filename,
                base_triangles,
                art_triangles,
                args.width,
                args.height,
                args.base_thickness + args.art_height,
            )
        else:
            write_3mf(
                out / filename,
                base_triangles,
                art_triangles,
                args.width,
                args.height,
                args.base_thickness + args.art_height,
            )
        piece_entries.append(
            {
                "filename": filename,
                "areaMm2": round(piece.area, 1),
                "baseTriangles": len(base_triangles),
                "artTriangles": len(art_triangles),
                "baseNonmanifoldEdges": nonmanifold_edges(base_triangles),
                "artNonmanifoldEdges": nonmanifold_edges(art_triangles) if art_triangles else 0,
            }
        )

    manifest = {
        "name": args.name,
        "mode": "surprise-multicolour-jigsaw",
        "format": args.format,
        "createdAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "pieceCount": len(pieces),
        "dimensionsMm": {
            "width": args.width,
            "height": args.height,
            "irregularOuterSilhouette": args.irregular,
            "sideBevel": True,
            "baseThickness": args.base_thickness,
            "totalHeight": args.base_thickness + args.art_height,
        },
        "bambuStudioImport": "Open each 3MF and choose Yes when Bambu asks to load as a single object with multiple parts.",
        "filamentAssignment": {
            "base_colour_1": 1,
            "reveal_colour_2": 2,
        },
        "pieces": piece_entries,
        "files": ["preview.png", *[entry["filename"] for entry in piece_entries]],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated surprise puzzle in {out}")
    print(json.dumps({"pieces": piece_entries}, indent=2))


if __name__ == "__main__":
    main()
