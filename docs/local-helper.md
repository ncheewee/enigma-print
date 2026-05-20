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
- `POST /print-piece` slices, uploads the G-code to the printer over FTPS, then sends a LAN MQTT print command.

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

- A small launch agent so the helper starts automatically after login.

## Local Printer Config

Printer control needs local-only credentials. Copy the example file and fill it in:

```bash
cp config/local_printer.example.json config/local_printer.json
```

`config/local_printer.json` is git-ignored. It needs:

- `printerHost`: printer IP address on the same LAN.
- `serialNumber`: printer serial number, used in the MQTT topic.
- `accessCode`: LAN access code shown by the printer/Bambu Handy/Studio LAN mode settings.

`printerHost` can change when DHCP gives the printer a new IP. The helper first tries the configured host, then scans the local ARP cache and finally the configured/local subnet for a device with both Bambu LAN ports open. When it finds exactly one match, it updates `config/local_printer.json`.

The current print path is experimental and intentionally local-only:

```text
3MF -> Bambu Studio CLI slice -> plate_1.gcode -> .gcode.3mf package -> printer FTPS upload -> MQTT project_file command
```

By default the helper uploads to `cache/<piece>.gcode.3mf` and sends a `project_file` MQTT command pointing at `Metadata/plate_1.gcode` inside that package. Some firmware versions may require LAN-only or developer mode for MQTT/FTPS control.

Security notes:

- The helper only accepts workspace-relative paths and rejects paths outside the EnigmaPrint folder.
- Keep secrets and printer credentials in the helper environment, never in GitHub Pages.
- The static dashboard can remain public; local printer control stays local.
