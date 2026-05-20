# EnigmaPrint — UI Design

Mobile-first dashboard for the Bambu Lab A1 mini weekly puzzle workflow.
Designed in Cowork mode, May 2026. Five screen mockups cover the full weekly loop.

---

## Design language

**Palette** — warm amber for active/today states, teal for completed/printed states, coral for primary actions (send to printer). All colours are drawn from a consistent 7-stop ramp so light and dark mode both work without adjustment.

**Layout pattern** — Focus view (Concept B): one piece at a time, full attention. Left/right nav arrows move through the week's history. A 7-dot progress strip below the 3D viewer shows the week at a glance without taking over the screen.

**3D viewer** — oblique projection of the puzzle piece slab in the active palette colour. Axis indicator (X/Y/Z) and a rotation handle hint signal that the model is interactive. Completed pieces switch the viewer to teal with a checkmark overlay.

---

## Screens

### screen-1-today.png — Today's piece

The main daily view. Shows Day 3 of 7 with the amber 3D model viewer. Left arrow navigates to past pieces; right arrow is dimmed (no future pieces yet). The coral "Send to A1 mini" button is the primary action — tapping it sends the `.3mf` file directly to the printer even when away from home. Print stats (estimated time, filament weight, printer status) sit below as secondary info.

### screen-2-past-piece.png — Past piece (navigated)

The same Focus layout but navigated left to Day 1. The 3D viewer switches to a dark teal background with a green checkmark badge on the piece — the "done" colorway. The print CTA is replaced by a read-only "Printed · Mon 19 May" chip. Stats show actuals (print time, filament used) rather than estimates.

### screen-3-week-complete.png — Week complete

All 7 progress dots fill teal. The 3D viewer shows the final piece with a `7/7` amber badge and confetti dots. The primary action changes from the coral print button to a large amber **"Piece it together →"** button — a pun that earns its place. This screen only appears after the seventh piece is marked printed.

### screen-4a-assembly.png — Assembly guide (before reveal)

Triggered by tapping "Piece it together →". Shows the 7 jigsaw pieces as proper interlocking SVG outlines (bezier tab/notch geometry — pieces would physically fit if cut). Pieces 1–6 are teal, piece 7 is amber to distinguish it as the final connector. Each piece is numbered in assembly order. The "Hidden until you build it" box with a dashed border and eye-off icon sits below — the image is withheld until the user physically assembles the puzzle.

### screen-4b-revealed.png — Design revealed (after tapping "Hidden until you build it")

The same jigsaw layout but each piece floods with its design colour (blue, amber, coral, green, etc.), suggesting a bas-relief landscape. The dashed mystery box is replaced by an amber "Week 21 · Geometry Fit" confirmation chip with a "tap to hide" affordance so the reveal is reversible. In the real implementation, each piece would use a `clipPath` over the actual AI-generated image, so the full composition only reads correctly once assembled.

---

## Colour reference

| Role | Hex | Used for |
|---|---|---|
| Amber 400 | `#EF9F27` | Active piece, "Piece it together" CTA, today state |
| Amber 100 | `#FAC775` | 3D piece top face, stats highlight |
| Coral 600 | `#D85A30` | Primary print action button |
| Teal 400 | `#1D9E75` | Completed/printed state, "Mark as assembled" CTA |
| Teal 200 | `#5DCAA5` | 3D viewer secondary faces, past-piece dots |
| Teal 50 | `#E1F5EE` | Jigsaw piece fill (before reveal) |

---

## Implementation notes

- All screens are mobile web (HTML/CSS/JS + localStorage), matching the existing `index.html` MVP approach.
- The 3D viewer is SVG-based (oblique projection) — no WebGL needed for the mockup fidelity shown.
- Jigsaw outlines use cubic bezier tab/notch paths. The 7-piece layout is 3+3+1 (two full rows plus a centred keystone piece).
- The "Send to A1 mini" action connects to the existing `local_helper.py` server (`http://127.0.0.1:4777`).
- Google Drive sync can be added later without changing the screen layout — only the data layer changes.
- If building with Codex, the five PNGs in this folder can be used directly as visual reference for each component.
