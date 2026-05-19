#!/usr/bin/env python3
"""Local helper for Enigma Print browser actions.

The GitHub Pages frontend is static and cannot safely control Bambu Studio by
itself. Run this helper on the Mac that has Bambu Studio installed, then the
frontend can ask localhost to open a generated piece.
"""

from __future__ import annotations

import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BAMBU_STUDIO = Path("/Applications/BambuStudio.app")
BAMBU_STUDIO_CLI = BAMBU_STUDIO / "Contents/MacOS/BambuStudio"
HOST = "127.0.0.1"
PORT = 4777


class Handler(BaseHTTPRequestHandler):
    server_version = "EnigmaPrintHelper/0.1"

    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json({"ok": True, "root": str(ROOT)})
            return
        self.send_error(404, "Unknown endpoint")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/open-piece":
            self.open_piece()
            return
        if path == "/slice-piece":
            self.slice_piece()
            return
        self.send_error(404, "Unknown endpoint")

    def open_piece(self) -> None:
        payload = self.read_json()
        relative_path = payload.get("path", "")
        piece_path = resolve_workspace_path(relative_path)
        if not piece_path.exists():
            self.send_error(404, f"File not found: {relative_path}")
            return
        subprocess.run(["open", "-a", str(BAMBU_STUDIO), str(piece_path)], check=True)
        self.send_json({"ok": True, "opened": str(piece_path)})

    def slice_piece(self) -> None:
        payload = self.read_json()
        relative_path = payload.get("path", "")
        piece_path = resolve_workspace_path(relative_path)
        if not piece_path.exists():
            self.send_error(404, f"File not found: {relative_path}")
            return
        if not BAMBU_STUDIO_CLI.exists():
            self.send_error(404, f"Bambu Studio CLI not found: {BAMBU_STUDIO_CLI}")
            return

        output_dir = ROOT / "generated" / "sliced" / piece_path.parent.name / piece_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [str(BAMBU_STUDIO_CLI), "--slice", "0", "--outputdir", str(output_dir), str(piece_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.send_json(
                {
                    "ok": False,
                    "returnCode": result.returncode,
                    "stdout": result.stdout[-4000:],
                    "stderr": result.stderr[-4000:],
                },
                status=500,
            )
            return

        outputs = [
            str(path.relative_to(ROOT))
            for path in sorted(output_dir.iterdir())
            if path.is_file()
        ]
        self.send_json({"ok": True, "sliced": str(piece_path), "outputDir": str(output_dir), "outputs": outputs})

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")


def resolve_workspace_path(relative_path: str) -> Path:
    candidate = (ROOT / relative_path).resolve()
    if not candidate.is_relative_to(ROOT):
        raise ValueError("Path must stay inside the EnigmaPrint workspace.")
    return candidate


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Enigma Print helper listening on http://{HOST}:{PORT}")
    print(f"Workspace root: {ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
