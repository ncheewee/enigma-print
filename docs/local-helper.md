# Local Helper

GitHub Pages hosts the Enigma Print dashboard, but browser JavaScript should not directly control Bambu Studio or the printer. The local helper is the bridge that runs on the Mac connected to Bambu Studio.

Start it from the project folder:

```bash
python3 scripts/local_helper.py
```

It listens on:

```text
http://127.0.0.1:4777
```

Current endpoints:

- `GET /health` confirms the helper is running.
- `POST /open-piece` opens a workspace-relative 3MF in Bambu Studio.
- `POST /slice-piece` runs Bambu Studio CLI slicing and writes G-code under `generated/sliced/<project>/<piece>/`. This is headless; it does not update the already-open Bambu Studio GUI.

Example request:

```bash
curl -X POST http://127.0.0.1:4777/open-piece \
  -H 'Content-Type: application/json' \
  -d '{"path":"generated/surprises/orbit-shrine-4pc-single/piece-01.3mf"}'
```

Slice request:

```bash
curl -X POST http://127.0.0.1:4777/slice-piece \
  -H 'Content-Type: application/json' \
  -d '{"path":"generated/surprises/orbit-shrine-4pc-single/piece-01.3mf"}'
```

Planned endpoints:

- `POST /print-piece` to send a sliced job to the printer once the local Bambu workflow is proven.
- A small launch agent so the helper starts automatically after login.

Security notes:

- The helper only accepts workspace-relative paths and rejects paths outside the EnigmaPrint folder.
- Keep secrets and printer credentials in the helper environment, never in GitHub Pages.
- The static dashboard can remain public; local printer control stays local.
