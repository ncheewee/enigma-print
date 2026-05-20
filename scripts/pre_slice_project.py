#!/usr/bin/env python3
"""Pre-slicing CLI tool for Enigma Print.

Slices all 3MF pieces in a project folder headlessly using the local Bambu Studio CLI
and compiles them into `.gcode.3mf` packages. This removes the need for a 24/7 Mac helper
at print time, as the pre-sliced assets can be uploaded directly from the cloud.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BAMBU_STUDIO = Path("/Applications/BambuStudio.app")
BAMBU_STUDIO_CLI = BAMBU_STUDIO / "Contents/MacOS/BambuStudio"


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-slice Enigma puzzle pieces.")
    parser.add_argument(
        "--project",
        type=str,
        required=True,
        help="Slug of the project (e.g. orbit-shrine-4pc-single) or absolute path to project directory.",
    )
    args = parser.parse_args()

    # Resolve project directory
    project_dir = Path(args.project)
    if not project_dir.is_absolute():
        # Try finding in generated/surprises or generated/
        candidate1 = ROOT / "generated" / "surprises" / args.project
        candidate2 = ROOT / "generated" / args.project
        if candidate1.exists():
            project_dir = candidate1
        elif candidate2.exists():
            project_dir = candidate2
        else:
            project_dir = ROOT / args.project

    if not project_dir.exists() or not project_dir.is_dir():
        print(f"Error: Project directory not found: {project_dir}")
        return

    manifest_path = project_dir / "manifest.json"
    if not manifest_path.exists():
        print(f"Error: manifest.json not found in {project_dir}")
        return

    print(f"Loading project from {project_dir}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pieces = manifest.get("pieces", [])
    if not pieces:
        print("Error: No pieces found in manifest.")
        return

    if not BAMBU_STUDIO_CLI.exists():
        print(f"Error: Bambu Studio CLI not found at: {BAMBU_STUDIO_CLI}")
        print("Please ensure Bambu Studio is installed in /Applications/")
        return

    # Slices output directory
    sliced_root = ROOT / "generated" / "sliced" / project_dir.name
    sliced_root.mkdir(parents=True, exist_ok=True)

    print(f"Slicing {len(pieces)} pieces. This will take up to 2-3 minutes...")

    for index, piece in enumerate(pieces, start=1):
        filename = piece.get("filename")
        piece_path = project_dir / filename
        if not piece_path.exists():
            # Try day-based naming fallback
            piece_path = project_dir / f"piece-{index:02d}.3mf"

        if not piece_path.exists():
            print(f"Warning: Piece file not found: {piece_path}, skipping.")
            continue

        print(f"\n--- Slicing Piece {index}/{len(pieces)}: {piece_path.name} ---")

        piece_slice_dir = sliced_root / piece_path.stem
        piece_slice_dir.mkdir(parents=True, exist_ok=True)

        # 1. Run Bambu Studio CLI slice
        print(f"Running Bambu Studio CLI on {piece_path.name}...")
        result = subprocess.run(
            [str(BAMBU_STUDIO_CLI), "--slice", "0", "--outputdir", str(piece_slice_dir), str(piece_path)],
            check=False,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"Error: Slicing failed for {piece_path.name}:")
            print(result.stderr)
            continue

        # Locate generated G-code
        outputs = sorted(path for path in piece_slice_dir.iterdir() if path.is_file())
        gcode_files = [path for path in outputs if path.suffix.lower() == ".gcode"]
        if not gcode_files:
            print(f"Error: Slicing finished but no .gcode file was generated for {piece_path.name}")
            continue

        gcode_path = gcode_files[0]
        print(f"G-code generated: {gcode_path.name}")

        # 2. Package G-code back into .gcode.3mf
        output_package_path = sliced_root / f"{piece_path.stem}.gcode.3mf"
        print(f"Packaging into {output_package_path.name}...")

        # Parse prediction values from result.json
        prediction = 0
        weight = 0.0
        result_json_path = piece_slice_dir / "result.json"
        if result_json_path.exists():
            try:
                slice_result = json.loads(result_json_path.read_text(encoding="utf-8"))
                plates = slice_result.get("sliced_plates") or []
                if plates:
                    prediction = int(float(plates[0].get("total_predication", 0)))
                    filaments = plates[0].get("filaments") or []
                    weight = sum(float(item.get("total_used_g", 0)) for item in filaments)
            except Exception as e:
                print(f"Warning: Could not parse result.json: {e}")

        # Write the zipped archive
        gcode_bytes = gcode_path.read_bytes()
        gcode_md5 = hashlib.md5(gcode_bytes).hexdigest()

        with zipfile.ZipFile(piece_path) as source, zipfile.ZipFile(
            output_package_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as package:
            existing = set()
            for item in source.infolist():
                if item.filename in {"Metadata/plate_1.gcode", "Metadata/plate_1.gcode.md5", "Metadata/plate_1.json"}:
                    continue
                if item.filename == "Metadata/model_settings.config":
                    package.writestr(item.filename, gcode_model_settings_xml())
                elif item.filename == "Metadata/slice_info.config":
                    package.writestr(item.filename, gcode_slice_info_xml(prediction, weight, piece_path.name))
                else:
                    package.writestr(item, source.read(item.filename))
                existing.add(item.filename)

            if "Metadata/model_settings.config" not in existing:
                package.writestr("Metadata/model_settings.config", gcode_model_settings_xml())
            if "Metadata/slice_info.config" not in existing:
                package.writestr("Metadata/slice_info.config", gcode_slice_info_xml(prediction, weight, piece_path.name))
            package.writestr("Metadata/plate_1.gcode", gcode_bytes)
            package.writestr("Metadata/plate_1.gcode.md5", gcode_md5)
            package.writestr("Metadata/plate_1.json", "{}")

        # Update the piece manifest details with sliced paths and stats
        piece["gcode3mfPath"] = f"generated/sliced/{project_dir.name}/{output_package_path.name}"
        piece["printTimeMinutes"] = int(prediction / 60) if prediction > 0 else 28
        piece["filamentWeightG"] = round(weight, 1) if weight > 0 else 14.0
        piece["status"] = "sliced"

        print(f"Successfully packaged piece {index}: {output_package_path.name}")
        print(f"Stats: {piece['printTimeMinutes']} min, {piece['filamentWeightG']}g filament")

        # Clean up temporary slicing directories to keep workspace neat
        for f in outputs:
            f.unlink()
        piece_slice_dir.rmdir()

    # Save updated manifest
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nPre-slicing complete! Updated manifest written to {manifest_path}")


def gcode_model_settings_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1"/>
    <metadata key="filament_volume_maps" value="0"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
    <metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/>
  </plate>
</config>
"""


def gcode_slice_info_xml(prediction: int, weight: float, object_name: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.06.00.51"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="extruder_type" value="0"/>
    <metadata key="nozzle_volume_type" value="0"/>
    <metadata key="printer_model_id" value="N1"/>
    <metadata key="nozzle_diameters" value="0.6"/>
    <metadata key="timelapse_type" value="0"/>
    <metadata key="prediction" value="{prediction}"/>
    <metadata key="weight" value="{weight:.2f}"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="false"/>
    <metadata key="label_object_enabled" value="false"/>
    <metadata key="filament_maps" value="1"/>
    <metadata key="limit_filament_maps" value="0"/>
    <object identify_id="901" name="{object_name}" skipped="false" />
    <filament id="1" tray_info_idx="GFA00" type="PLA" color="#163D3A" used_g="{weight:.2f}" group_id="0" nozzle_diameter="0.60" volume_type="Standard"/>
    <layer_filament_lists>
      <layer_filament_list filament_list="0" layer_ranges="0 9999" />
    </layer_filament_lists>
  </plate>
</config>
"""


if __name__ == "__main__":
    main()
