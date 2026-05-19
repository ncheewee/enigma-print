# Enigma Print

Enigma Print is a lightweight MVP for managing weekly AI-generated 3D puzzle projects for a Bambu Lab A1 mini.

The first version is intentionally static:

- Open `index.html` in a browser.
- Projects are stored in `localStorage`.
- Export a project manifest as JSON.
- Use the same manifest shape later as the Google Drive backend document.

## MVP Workflow

1. Create one weekly puzzle project.
2. Generate or attach seven daily `.3mf` files.
3. Print the next pending piece overnight.
4. Mark it printed in the dashboard.
5. At the end of the week, assemble the final puzzle.

## Suggested Google Drive Backend

Use one Drive folder as the app backend:

```text
EnigmaPrint/
  projects/
    week-20-clockwork-garden/
      manifest.json
      source-hidden.png
      day-01.stl
      day-01.3mf
      day-02.stl
      day-02.3mf
      ...
```

The app can later replace `localStorage` with a Drive adapter that reads and writes `manifest.json` files.

Recommended manifest fields:

```json
{
  "id": "project-current",
  "name": "Week 20: Clockwork Garden",
  "slug": "week-20-clockwork-garden",
  "status": "active",
  "summary": "A seven-day AI generated bas-relief jigsaw.",
  "targetPrinter": "A1 mini",
  "files": [],
  "pieces": []
}
```

## Next Build Step

The first generator stage is now available:

```bash
python3 scripts/generate_weekly_puzzle.py \
  --name "Week 21: Geometry Fit Test" \
  --out generated \
  --start-date 2026-05-11
```

It creates seven interlocking STL files, a preview SVG, a hidden final reveal SVG, and a manifest.
Use **Import manifest** in the dashboard to add the generated project.

For quick fit testing, install the local generator dependency and create pyjigsaw-based coupons:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/generate_pyjigsaw_coupons.py --clearance 0.3 --chamfer 0.5
```

Print the two coupon STLs in `generated/pyjigsaw-coupons/0p30` to pick a real clearance before making the full puzzle.

For the first multicolour jigsaw logo test:

```bash
.venv/bin/python scripts/generate_logo_jigsaw.py \
  --text "Project Opus" \
  --out generated/logo/project-opus-jigsaw-2x2
```

This creates four jigsaw pieces, each split into a base-colour STL and raised text-colour STL.

The current known-good multicolour Bambu 3MF path is:

```bash
.venv/bin/python scripts/generate_surprise_jigsaw_3mf.py \
  --out generated/surprises/orbit-shrine-4pc-v6-reference-style \
  --name "Orbit Shrine" \
  --design orbit-shrine
```

This emits one `.3mf` per puzzle piece. In Bambu Studio, `base_colour_1` should open on filament `1` and `reveal_colour_2` should open on filament `2`. The details are documented in `docs/generator.md`.

For one-click local opening from the published dashboard, run:

```bash
python3 scripts/local_helper.py
```

The helper listens on `http://127.0.0.1:4777` and can open selected workspace 3MF files in Bambu Studio. Slicing and print submission are the next local-helper endpoints to add.

The next practical step is the relief-art generator:

```text
scripts/generate_weekly_puzzle.py
  -> create or load AI image
  -> convert image to printable relief
  -> split relief into seven interlocking pieces
  -> export STL and 3MF files
  -> write manifest.json
```

After that, Google Drive sync can be added with either:

- Google Picker and Drive API in the browser, or
- a tiny local sync script using a service account or OAuth desktop flow.
