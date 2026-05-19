# Generator Plan

The generator is built in stages so beauty and printability can improve without making the first version fragile.

## Stage 1: Geometry Fit Test

Implemented in `scripts/generate_weekly_puzzle.py`.

This stage creates:

- seven interlocking daily STL pieces
- a `preview.svg` layout
- a `source-hidden.svg` full reveal asset
- a dashboard-compatible `manifest.json`

The output now includes a raised-line relief motif. The geometry is still intentionally conservative: flat-bottomed pieces, chunky side connectors, and no supports.

## Jigsaw Coupon Tests

Use `scripts/generate_pyjigsaw_coupons.py` before committing to a full puzzle edge style. This uses the MIT-licensed `pyjigsaw` package for real jigsaw SVG paths, then converts those paths into STL.

Set up the local dependency once:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Generate the current kerf-based 0.50 mm clearance coupon pair with 0.5 mm top and bottom bevel bands:

```bash
.venv/bin/python scripts/generate_pyjigsaw_coupons.py \
  --clearance 0.5 \
  --chamfer 0.5 \
  --bevel-inset 0.25 \
  --out generated/pyjigsaw-coupons/kerf-0p50
```

Default outputs are two separate pieces:

```text
generated/pyjigsaw-coupons/kerf-0p50/pyjigsaw-0p50-piece-01.stl
generated/pyjigsaw-coupons/kerf-0p50/pyjigsaw-0p50-piece-02.stl
generated/pyjigsaw-coupons/kerf-0p50/preview.svg
```

Here, `--clearance` means cutter kerf / cut-line width. The shared jigsaw cut curve is offset by half that value on each side, so `--clearance 0.5` means about 0.25 mm removed from each mating edge.

The bevel keeps the nominal jigsaw outline through the middle of the part, but insets the first and last 0.5 mm of height by `--bevel-inset`. This reduces first-layer elephant-foot catching and softens the top edge without changing the core fit surface.

Example:

```bash
python3 scripts/generate_weekly_puzzle.py \
  --name "Week 21: Geometry Fit Test" \
  --out generated \
  --start-date 2026-05-11
```

## Stage 2: AI-Derived Relief Art

Next, the procedural motif should be replaced or augmented with AI-derived art:

1. Generate or provide a square image.
2. Normalize it into a high-contrast grayscale heightmap.
3. Clamp fine detail so the print remains smooth.
4. Apply the heightmap across the full board.
5. Split the relief into the seven existing pieces.

## Multicolour Logo Jigsaw Test

Use `scripts/generate_logo_jigsaw.py` to create a first multicolour-ready jigsaw model.

```bash
.venv/bin/python scripts/generate_logo_jigsaw.py \
  --text "Project Opus" \
  --out generated/logo/project-opus-jigsaw-2x2
```

This produces four jigsaw pieces. Each piece has two aligned STL bodies:

```text
piece-01-colour-1-base.stl
piece-01-colour-2-text.stl
...
piece-04-colour-1-base.stl
piece-04-colour-2-text.stl
```

Import each base/text pair together in Bambu Studio and assign different filament colours. The base uses the successful 2x2 fit recipe: `0.1 mm` inward shrink, `0.5 mm` top-down corner radius, and `1.0 mm` bevel height.

For a smaller 20 mm-ish piece test with true 3MF material bodies:

```bash
.venv/bin/python scripts/generate_logo_jigsaw.py \
  --format 3mf \
  --text "Project Opus" \
  --width 40 \
  --height 40 \
  --out generated/logo/project-opus-3mf-2x2-20mm \
  --base-thickness 2.4 \
  --text-height 1.6 \
  --bevel-height 1.0 \
  --bevel-inset 0.25
```

This outputs exactly four `.3mf` files, one per physical puzzle piece. Each 3MF contains a base mesh and a raised text mesh with separate material assignments.

## Stage 3: Weekly Mystery

Finally, add the weekly ritual:

- prompt generation
- hidden source image
- STL/3MF export pack
- Google Drive folder write
- dashboard import/sync

## Known-Good Bambu 3MF Recipe

Use `scripts/generate_surprise_jigsaw_3mf.py` for the current irregular multicolour puzzle pieces.

Known-good command:

```bash
.venv/bin/python scripts/generate_surprise_jigsaw_3mf.py \
  --out generated/surprises/orbit-shrine-4pc-v6-reference-style \
  --name "Orbit Shrine" \
  --design orbit-shrine
```

The working 3MF format is based on `reference-bambu-filament2.3mf`, which was manually saved from Bambu Studio after assigning:

- `base_colour_1` to filament `1`
- `reveal_colour_2` to filament `2`

Important details:

- The file must use one `3D/3dmodel.model`, not separate `3D/Objects/object_*.model` component files.
- Mesh object `1` is the base body.
- Mesh object `2` is the reveal/raised art body.
- Parent object `3` contains components for objects `1` and `2`.
- `Metadata/model_settings.config` must describe parent object `3` and assign part `2` to extruder `2`.
- `Metadata/project_settings.config` should stay close to Bambu Studio's saved baseline. Do not force `has_filament_switcher = 1` or project-level `filament_map = ["1", "2"]`; Studio's saved working file kept `has_filament_switcher = 0` and `filament_map = ["1", "1"]`.
- Keep the thumbnail relationship structure and placeholder thumbnail files from the Studio-saved reference. Without these, Bambu Studio may open the file inconsistently.

Validation:

```bash
for f in generated/surprises/orbit-shrine-4pc-v6-reference-style/piece-*.3mf; do
  python3 -m zipfile -t "$f"
  /Applications/BambuStudio.app/Contents/MacOS/BambuStudio --info "$f" |
    rg 'manifold|number_of_parts|number_of_facets|size_'
done
```

Expected:

- each file opens one-at-a-time in Bambu Studio
- `base_colour_1` shows `Fila. 1`
- `reveal_colour_2` shows `Fila. 2`
- Bambu CLI reports `manifold = yes` and `number_of_parts = 2`

Avoid these failed approaches:

- Generic 3MF with two top-level material objects plus `Metadata/model_settings.config`: geometry imports, but Bambu assigns both parts to filament `1`.
- Hand-built Bambu project with separate `3D/Objects/object_*.model` files: Bambu CLI may see geometry, but Studio may report invalid configuration or no geometry when opened directly.
- Overriding project-level filament settings aggressively: it caused inconsistent import behaviour. The reliable assignment is in `model_settings.config` parts, not the project-level filament map.
