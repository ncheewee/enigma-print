#!/usr/bin/env python3
"""Generate tiny two-colour 3MF diagnostics for Bambu Studio."""

from __future__ import annotations

import argparse
import json
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

from PIL import Image, ImageDraw

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


def mark_triangles(width: float, height: float, base_z: float, top_z: float) -> List[Triangle]:
    """Raised colour-2 tiles made only of separated rectangular prisms."""
    bars = [
        (8, 8, 18, 16),
        (23, 8, 33, 16),
        (38, 8, 48, 16),
        (13, 21, 23, 29),
        (28, 21, 38, 29),
        (43, 21, 53, 29),
    ]
    sx = width / 64.0
    sy = height / 40.0
    triangles: List[Triangle] = []
    for x0, y0, x1, y1 in bars:
        triangles.extend(box_triangles(x0 * sx, y0 * sy, x1 * sx, y1 * sy, base_z, top_z))
    return triangles


def centered(triangles: Sequence[Triangle], width: float, height: float) -> List[Triangle]:
    return [
        tuple((x - width / 2, y - height / 2, z) for x, y, z in tri)  # type: ignore[misc]
        for tri in triangles
    ]


def indexed_mesh(triangles: Sequence[Triangle]):
    vertices: List[Vertex] = []
    vertex_index: dict[Vertex, int] = {}
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


def mesh_model_xml(object_id: int, triangles: Sequence[Triangle], name: str = "") -> str:
    vertices, triangle_indices = indexed_mesh(triangles)
    name_attr = f' name="{name}"' if name else ""
    vertices_xml = "\n".join(f'     <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in vertices)
    triangles_xml = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in triangle_indices)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
  <object id="{object_id}" p:UUID="0000000{object_id}-81cb-4c03-9d28-80fed5dfa1dc" type="model"{name_attr}>
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


def root_bambu_model_xml(width: float, height: float, total_z: float) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">BambuStudio-02.06.00.51</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <metadata name="CreationDate">{datetime.now().date().isoformat()}</metadata>
 <metadata name="Title">Enigma Print multicolour diagnostic</metadata>
 <resources>
  <object id="2" p:UUID="00000002-61cb-4c03-9d28-80fed5dfa1dc" type="model" name="enigma_multicolour_single_piece">
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


def generic_model_xml(base: Sequence[Triangle], mark: Sequence[Triangle]) -> str:
    base_object = generic_object_xml(1, "base_colour_1", base, 0)
    mark_object = generic_object_xml(2, "raised_colour_2", mark, 1)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources>
  <basematerials id="1">
   <base name="Base colour" displaycolor="#173F3AFF"/>
   <base name="Raised colour" displaycolor="#F8F4DFFF"/>
  </basematerials>
  {base_object}
  {mark_object}
 </resources>
 <build>
  <item objectid="1"/>
  <item objectid="2"/>
 </build>
</model>
"""


def generic_object_xml(object_id: int, name: str, triangles: Sequence[Triangle], material_index: int) -> str:
    vertices, triangle_indices = indexed_mesh(triangles)
    vertices_xml = "\n".join(f'    <vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in vertices)
    triangles_xml = "\n".join(
        f'    <triangle v1="{a}" v2="{b}" v3="{c}" pid="1" p1="{material_index}" p2="{material_index}" p3="{material_index}"/>'
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


def model_settings_xml(base_faces: int, mark_faces: int) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <object id="2">
    <metadata key="name" value="enigma_multicolour_single_piece"/>
    <metadata key="extruder" value="1"/>
    <metadata face_count="{base_faces + mark_faces}"/>
    <part id="1" subtype="normal_part">
      <metadata key="name" value="base_colour_1"/>
      <metadata key="extruder" value="1"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="enigma_multicolour_single_piece.3mf"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="0"/>
      <mesh_stat face_count="{base_faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
    </part>
    <part id="3" subtype="normal_part">
      <metadata key="name" value="raised_colour_2"/>
      <metadata key="extruder" value="2"/>
      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>
      <metadata key="source_file" value="enigma_multicolour_single_piece.3mf"/>
      <metadata key="source_object_id" value="0"/>
      <metadata key="source_volume_id" value="1"/>
      <mesh_stat face_count="{mark_faces}" edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>
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
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
      <metadata key="identify_id" value="901"/>
    </model_instance>
  </plate>
  <assemble>
   <assemble_item object_id="2" instance_id="0" transform="1 0 0 0 1 0 0 0 1 0 0 0" offset="0 0 0" />
  </assemble>
</config>
"""


def cut_information_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<objects>
 <object id="1">
  <cut_id id="0" check_sum="1" connectors_cnt="0"/>
 </object>
 <object id="3">
  <cut_id id="0" check_sum="1" connectors_cnt="0"/>
 </object>
</objects>
"""


def project_settings_json(template_3mf: Path) -> str:
    with zipfile.ZipFile(template_3mf) as package:
        settings = json.loads(package.read("Metadata/project_settings.config"))
    patch_arrays = {
        "filament_colour": ["#173F3A", "#F8F4DF"],
        "filament_type": ["PLA", "PLA"],
        "filament_settings_id": ["Bambu PLA Basic 200C", "Bambu PLA Basic 200C"],
        "filament_ids": ["GFA00", "GFA00"],
        "filament_map": ["1", "2"],
        "filament_colour_type": ["1", "1"],
        "default_filament_colour": ["", ""],
        "default_filament_profile": ["Bambu PLA Basic @BBL A1M", "Bambu PLA Basic @BBL A1M"],
        "filament_is_support": ["0", "0"],
        "filament_soluble": ["0", "0"],
        "filament_printable": ["1", "1"],
    }
    for key, value in patch_arrays.items():
        settings[key] = value
    settings["has_filament_switcher"] = "1"
    settings["single_extruder_multi_material"] = "1"
    settings["printer_model"] = "Bambu Lab A1 mini"
    return json.dumps(settings, indent=4)


def rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def model_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/Objects/object_1.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/3D/Objects/object_3.model" Id="rel-2" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def content_types_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="application/octet-stream"/>
</Types>
"""


def write_bambu_project(path: Path, base: Sequence[Triangle], mark: Sequence[Triangle], args: argparse.Namespace) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types_xml())
        package.writestr("_rels/.rels", rels_xml())
        package.writestr("3D/3dmodel.model", root_bambu_model_xml(args.width, args.height, args.base_thickness + args.mark_height))
        package.writestr("3D/_rels/3dmodel.model.rels", model_rels_xml())
        package.writestr("3D/Objects/object_1.model", mesh_model_xml(1, centered(base, args.width, args.height), "base_colour_1"))
        package.writestr("3D/Objects/object_3.model", mesh_model_xml(3, centered(mark, args.width, args.height), "raised_colour_2"))
        package.writestr("Metadata/project_settings.config", project_settings_json(Path(args.template_3mf)))
        package.writestr("Metadata/model_settings.config", model_settings_xml(len(base), len(mark)))
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
        package.writestr("Metadata/cut_information.xml", cut_information_xml())


def write_generic(path: Path, base: Sequence[Triangle], mark: Sequence[Triangle]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types_xml())
        package.writestr("_rels/.rels", rels_xml())
        package.writestr("3D/3dmodel.model", generic_model_xml(base, mark))


def write_single_object_3mf(path: Path, name: str, triangles: Sequence[Triangle]) -> None:
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
 <resources>
  {generic_object_xml(1, name, triangles, 0)}
 </resources>
 <build>
  <item objectid="1"/>
 </build>
</model>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", content_types_xml())
        package.writestr("_rels/.rels", rels_xml())
        package.writestr("3D/3dmodel.model", body)


def write_ascii_stl(path: Path, name: str, triangles: Sequence[Triangle]) -> None:
    def normal(_: Triangle) -> Vertex:
        return (0.0, 0.0, 0.0)

    lines = [f"solid {name}"]
    for triangle in triangles:
        nx, ny, nz = normal(triangle)
        lines.append(f"  facet normal {nx:.6f} {ny:.6f} {nz:.6f}")
        lines.append("    outer loop")
        for x, y, z in triangle:
            lines.append(f"      vertex {x:.6f} {y:.6f} {z:.6f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append(f"endsolid {name}")
    path.write_text("\n".join(lines), encoding="ascii")


def write_preview(path: Path, width: float, height: float) -> None:
    scale = 8
    image = Image.new("RGB", (int(width * scale), int(height * scale)), "#173f3a")
    draw = ImageDraw.Draw(image)
    for tri in mark_triangles(width, height, 0, 1):
        xs = [point[0] for point in tri]
        ys = [point[1] for point in tri]
        if max(ys) - min(ys) > 0 and max(xs) - min(xs) > 0:
            draw.rectangle(
                [min(xs) * scale, (height - max(ys)) * scale, max(xs) * scale, (height - min(ys)) * scale],
                fill="#f8f4df",
            )
    image.save(path)


def nonmanifold_edges(triangles: Sequence[Triangle]) -> int:
    vertices, triangle_indices = indexed_mesh(triangles)
    del vertices
    edges: Counter[Tuple[int, int]] = Counter()
    for a, b, c in triangle_indices:
        for edge in [(a, b), (b, c), (c, a)]:
            edges[tuple(sorted(edge))] += 1
    return sum(1 for count in edges.values() if count != 2)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Bambu multicolour 3MF diagnostics.")
    parser.add_argument("--out", default="generated/logo/multicolor-single-piece-v2")
    parser.add_argument("--width", type=float, default=40.0)
    parser.add_argument("--height", type=float, default=25.0)
    parser.add_argument("--base-thickness", type=float, default=2.4)
    parser.add_argument("--mark-height", type=float, default=1.2)
    parser.add_argument(
        "--template-3mf",
        default="generated/week-23-hidden-artifact/week-23-hidden-artifact-day-02.3mf",
        help="Existing Bambu Studio 3MF to borrow A1 mini project defaults from.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    base = box_triangles(0, 0, args.width, args.height, 0, args.base_thickness)
    mark = mark_triangles(args.width, args.height, args.base_thickness, args.base_thickness + args.mark_height)
    write_generic(out / "opus-colour-test.3mf", base, mark)
    write_single_object_3mf(out / "base-colour-1.3mf", "base_colour_1", base)
    write_single_object_3mf(out / "raised-colour-2.3mf", "raised_colour_2", mark)
    write_ascii_stl(out / "base-colour-1.stl", "base_colour_1", base)
    write_ascii_stl(out / "raised-colour-2.stl", "raised_colour_2", mark)
    write_preview(out / "preview.png", args.width, args.height)
    manifest = {
        "name": "Multicolour single-piece diagnostic",
        "mode": "bambu-project-3mf",
        "createdAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "files": [
            "opus-colour-test.3mf",
            "base-colour-1.3mf",
            "raised-colour-2.3mf",
            "base-colour-1.stl",
            "raised-colour-2.stl",
            "preview.png",
        ],
        "bambuStudioImport": "Open opus-colour-test.3mf and choose Yes when Bambu asks to load as a single object with multiple parts.",
        "dimensionsMm": {
            "width": args.width,
            "height": args.height,
            "baseThickness": args.base_thickness,
            "totalHeight": args.base_thickness + args.mark_height,
        },
        "meshChecks": {
            "baseNonmanifoldEdges": nonmanifold_edges(base),
            "markNonmanifoldEdges": nonmanifold_edges(mark),
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated diagnostics in {out}")
    print(json.dumps(manifest["meshChecks"], indent=2))


if __name__ == "__main__":
    main()
