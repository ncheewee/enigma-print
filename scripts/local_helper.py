#!/usr/bin/env python3
"""Local helper for Enigma Print browser actions.

The GitHub Pages frontend is static and cannot safely control Bambu Studio by
itself. Run this helper on the Mac that has Bambu Studio installed, then the
frontend can ask localhost to open a generated piece.
"""

from __future__ import annotations

import ftplib
import json
import socket
import ssl
import struct
import subprocess
import time
from ipaddress import ip_network
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BAMBU_STUDIO = Path("/Applications/BambuStudio.app")
BAMBU_STUDIO_CLI = BAMBU_STUDIO / "Contents/MacOS/BambuStudio"
PRINTER_CONFIG = ROOT / "config" / "local_printer.json"
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
        if path == "/print-piece":
            self.print_piece()
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

        try:
            sliced = slice_piece_to_gcode(piece_path)
        except HelperError as error:
            self.send_json(error.payload, status=error.status)
            return

        self.send_json(
            {
                "ok": True,
                "sliced": str(piece_path),
                "outputDir": str(sliced["output_dir"]),
                "outputs": [str(path.relative_to(ROOT)) for path in sliced["outputs"]],
                "gcode": str(sliced["gcode"].relative_to(ROOT)),
            }
        )

    def print_piece(self) -> None:
        payload = self.read_json()
        relative_path = payload.get("path", "")
        piece_path = resolve_workspace_path(relative_path)
        if not piece_path.exists():
            self.send_error(404, f"File not found: {relative_path}")
            return

        try:
            config = load_printer_config()
            sliced = slice_piece_to_gcode(piece_path)
            print_result = send_gcode_to_printer(sliced["gcode"], config)
        except HelperError as error:
            self.send_json(error.payload, status=error.status)
            return

        self.send_json(
            {
                "ok": True,
                "piece": str(piece_path.relative_to(ROOT)),
                "gcode": str(sliced["gcode"].relative_to(ROOT)),
                **print_result,
            }
        )

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


class HelperError(Exception):
    def __init__(self, message: str, status: int = 500, **extra) -> None:
        super().__init__(message)
        self.status = status
        self.payload = {"ok": False, "message": message, **extra}


def slice_piece_to_gcode(piece_path: Path) -> dict:
    if not BAMBU_STUDIO_CLI.exists():
        raise HelperError(f"Bambu Studio CLI not found: {BAMBU_STUDIO_CLI}", status=404)

    output_dir = ROOT / "generated" / "sliced" / piece_path.parent.name / piece_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [str(BAMBU_STUDIO_CLI), "--slice", "0", "--outputdir", str(output_dir), str(piece_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HelperError(
            "Bambu Studio CLI slicing failed.",
            status=500,
            returnCode=result.returncode,
            stdout=result.stdout[-4000:],
            stderr=result.stderr[-4000:],
        )

    outputs = sorted(path for path in output_dir.iterdir() if path.is_file())
    gcode_files = [path for path in outputs if path.suffix.lower() == ".gcode"]
    if not gcode_files:
        raise HelperError("Bambu Studio CLI finished but did not create a .gcode file.", status=500)
    return {"output_dir": output_dir, "outputs": outputs, "gcode": gcode_files[0]}


def load_printer_config() -> dict:
    if not PRINTER_CONFIG.exists():
        raise HelperError(
            f"Printer config missing: {PRINTER_CONFIG.relative_to(ROOT)}",
            status=412,
            nextStep="Copy config/local_printer.example.json to config/local_printer.json and fill in printerHost, serialNumber, and accessCode.",
        )
    config = json.loads(PRINTER_CONFIG.read_text(encoding="utf-8"))
    required = ["serialNumber", "accessCode"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise HelperError(
            f"Printer config missing required field(s): {', '.join(missing)}",
            status=412,
        )
    return config


def send_gcode_to_printer(gcode_path: Path, config: dict) -> dict:
    host = resolve_printer_host(config)
    remote_name = config.get("remoteFilename") or f"cache/enigma-{gcode_path.parent.parent.name}-{gcode_path.parent.name}.gcode"
    upload_gcode_ftps(gcode_path, remote_name, config, host)
    command = build_print_command(remote_name, config)
    publish_mqtt(config, command, host)
    return {
        "printerHost": host,
        "remoteFilename": remote_name,
        "command": command,
    }


def resolve_printer_host(config: dict) -> str:
    configured = config.get("printerHost")
    if configured and host_has_ports(configured, config):
        return configured

    cached = discover_from_arp(config)
    if cached:
        config["printerHost"] = cached
        save_printer_config(config)
        return cached

    scanned = discover_on_subnet(config)
    if scanned:
        config["printerHost"] = scanned
        save_printer_config(config)
        return scanned

    raise HelperError(
        "Could not discover Bambu printer on LAN.",
        status=502,
        configuredHost=configured,
        nextStep="Check that the printer is awake, on the same Wi-Fi/LAN, and LAN mode is enabled.",
    )


def discover_from_arp(config: dict) -> str | None:
    result = subprocess.run(["arp", "-a"], capture_output=True, text=True, check=False)
    candidates = []
    for line in result.stdout.splitlines():
        if "(" not in line or ")" not in line:
            continue
        candidate = line.split("(", 1)[1].split(")", 1)[0]
        if host_has_ports(candidate, config, timeout=1.0):
            candidates.append(candidate)
    if len(candidates) == 1:
        return candidates[0]
    return config.get("printerHost") if config.get("printerHost") in candidates else None


def discover_on_subnet(config: dict) -> str | None:
    subnet = config.get("subnet") or local_ipv4_subnet()
    if not subnet:
        return None
    candidates = []
    for ip in ip_network(subnet, strict=False).hosts():
        candidate = str(ip)
        if host_has_ports(candidate, config, timeout=0.35):
            candidates.append(candidate)
            if len(candidates) > 1:
                break
    if len(candidates) == 1:
        return candidates[0]
    return None


def local_ipv4_subnet() -> str | None:
    result = subprocess.run(["ifconfig", "en0"], capture_output=True, text=True, check=False)
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 4 and parts[0] == "inet":
            return f"{parts[1]}/24"
    return None


def host_has_ports(host: str, config: dict, timeout: float = 1.0) -> bool:
    return can_connect(host, int(config.get("mqttPort", 8883)), timeout) and can_connect(
        host, int(config.get("ftpPort", 990)), timeout
    )


def can_connect(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def save_printer_config(config: dict) -> None:
    PRINTER_CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def upload_gcode_ftps(gcode_path: Path, remote_name: str, config: dict, host: str) -> None:
    port = int(config.get("ftpPort", 990))
    username = config.get("username", "bblp")
    password = config["accessCode"]
    timeout = int(config.get("networkTimeout", 60))
    try:
        with ImplicitFTP_TLS(host=host, user=username, passwd=password, port=port, timeout=timeout) as ftp:
            ftp.set_pasv(bool(config.get("ftpPassive", True)))
            ftp.prot_p()
            with gcode_path.open("rb") as handle:
                try:
                    ftp.storbinary(f"STOR {remote_name}", handle, blocksize=64 * 1024)
                except (socket.timeout, TimeoutError, OSError) as error:
                    if not is_timeout_error(error):
                        raise
                    if not remote_file_exists_with_config(remote_name, config, host):
                        raise
    except Exception as error:
        raise HelperError(f"FTPS upload failed: {error}", status=502) from error


def remote_file_exists(ftp: ftplib.FTP, remote_name: str) -> bool:
    try:
        directory, filename = remote_name.rsplit("/", 1)
    except ValueError:
        directory, filename = "", remote_name

    current = ftp.pwd()
    try:
        if directory:
            ftp.cwd(directory)
        return filename in ftp.nlst()
    finally:
        try:
            ftp.cwd(current)
        except Exception:
            pass


def remote_file_exists_with_config(remote_name: str, config: dict, host: str) -> bool:
    port = int(config.get("ftpPort", 990))
    username = config.get("username", "bblp")
    password = config["accessCode"]
    timeout = int(config.get("networkTimeout", 60))
    with ImplicitFTP_TLS(host=host, user=username, passwd=password, port=port, timeout=timeout) as ftp:
        ftp.set_pasv(bool(config.get("ftpPassive", True)))
        ftp.prot_p()
        return remote_file_exists(ftp, remote_name)


def is_timeout_error(error: BaseException) -> bool:
    return isinstance(error, (socket.timeout, TimeoutError)) or getattr(error, "errno", None) in {60, 110}


def build_print_command(remote_name: str, config: dict) -> dict:
    sequence_id = str(int(time.time()))
    command = config.get("printCommand", "gcode_file")
    if command == "gcode_file":
        return {
            "print": {
                "sequence_id": sequence_id,
                "command": "gcode_file",
                "param": f"/{remote_name.lstrip('/')}",
            }
        }

    return {
        "print": {
            "sequence_id": sequence_id,
            "command": command,
            "param": remote_name,
            "subtask_id": "0",
            "use_ams": False,
            "timelapse": False,
            "flow_cali": bool(config.get("flowCalibration", False)),
            "bed_leveling": bool(config.get("bedLeveling", True)),
            "vibration_cali": bool(config.get("vibrationCalibration", False)),
            "layer_inspect": False,
        }
    }


def publish_mqtt(config: dict, payload: dict, host: str) -> None:
    port = int(config.get("mqttPort", 8883))
    username = config.get("username", "bblp")
    password = config["accessCode"]
    serial = config["serialNumber"]
    topic = config.get("mqttTopic", f"device/{serial}/request").format(serial=serial)
    client_id = config.get("clientId", serial)
    context = ssl._create_unverified_context()

    try:
        with socket.create_connection((host, port), timeout=15) as raw:
            with context.wrap_socket(raw, server_hostname=host) as sock:
                mqtt_connect(sock, client_id, username, password)
                mqtt_publish(sock, topic, json.dumps(payload, separators=(",", ":")))
                sock.sendall(bytes([0xE0, 0x00]))
    except Exception as error:
        raise HelperError(f"MQTT print command failed: {error}", status=502, command=payload) from error


class ImplicitFTP_TLS(ftplib.FTP_TLS):
    def __init__(self, *args, port: int = 990, **kwargs) -> None:
        self._implicit_port = port
        super().__init__(*args, **kwargs)

    def connect(self, host="", port=0, timeout=-999, source_address=None):  # type: ignore[override]
        if port == 0:
            port = self._implicit_port
        if host:
            self.host = host
        if timeout != -999:
            self.timeout = timeout
        self.sock = socket.create_connection((self.host, port), self.timeout, source_address)
        self.af = self.sock.family
        self.sock = self.context.wrap_socket(self.sock, server_hostname=self.host)
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome


def mqtt_connect(sock: ssl.SSLSocket, client_id: str, username: str, password: str) -> None:
    variable_header = mqtt_string("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
    payload = mqtt_string(client_id) + mqtt_string(username) + mqtt_string(password)
    sock.sendall(bytes([0x10]) + mqtt_remaining_length(len(variable_header) + len(payload)) + variable_header + payload)
    response = sock.recv(4)
    if response != b"\x20\x02\x00\x00":
        raise RuntimeError(f"Unexpected MQTT CONNACK: {response!r}")


def mqtt_publish(sock: ssl.SSLSocket, topic: str, payload: str) -> None:
    body = mqtt_string(topic) + payload.encode("utf-8")
    sock.sendall(bytes([0x30]) + mqtt_remaining_length(len(body)) + body)


def mqtt_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("!H", len(encoded)) + encoded


def mqtt_remaining_length(length: int) -> bytes:
    output = bytearray()
    while True:
        encoded = length % 128
        length //= 128
        if length > 0:
            encoded |= 128
        output.append(encoded)
        if length == 0:
            return bytes(output)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Enigma Print helper listening on http://{HOST}:{PORT}")
    print(f"Workspace root: {ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
