"""Moonraker integration with explicit upload and print-start steps."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core import OrcaError, _existing_file, output_root


def _base_url() -> str:
    raw = os.environ.get("MOONRAKER_URL", "").strip()
    if not raw:
        raise OrcaError("Set MOONRAKER_URL, for example http://printer.local:7125")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise OrcaError("MOONRAKER_URL must be an http(s) URL without embedded credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise OrcaError("MOONRAKER_URL must contain only scheme, host, and port")
    return raw.rstrip("/")


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    key = os.environ.get("MOONRAKER_API_KEY", "").strip()
    if key:
        headers["X-Api-Key"] = key
    return headers


def _request(path: str, method: str = "GET", data: bytes | None = None,
             content_type: str | None = None) -> Any:
    headers = _headers()
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise OrcaError(f"Moonraker HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise OrcaError(f"Moonraker request failed: {exc}") from exc
    if not isinstance(payload, dict) or "error" in payload:
        raise OrcaError(f"Moonraker returned an error: {payload}")
    return payload.get("result", payload)


def printer_status() -> dict[str, Any]:
    info = _request("/server/info")
    query = _request("/printer/objects/query?webhooks&print_stats&virtual_sdcard")
    status = query.get("status", {})
    return {"moonraker_version": info.get("moonraker_version"),
            "klippy_connected": info.get("klippy_connected"),
            "klippy_state": info.get("klippy_state"),
            "webhooks": status.get("webhooks"),
            "print_stats": status.get("print_stats"),
            "virtual_sdcard": status.get("virtual_sdcard")}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload_gcode(path: str) -> dict[str, Any]:
    source = _existing_file(path, "G-code", {".gcode"})
    if source.stat().st_size > 100 * 1024 * 1024:
        raise OrcaError("G-code exceeds the 100 MiB upload limit")
    if source.stat().st_size == 0:
        raise OrcaError("G-code file is empty")
    safe_stem = re.sub(r"[^A-Za-z0-9_.-]", "_", source.stem)[:60].strip("._") or "print"
    upload_id = uuid.uuid4().hex
    remote_name = f"{safe_stem}-{upload_id[:8]}.gcode"
    boundary = "----cad-to-print-" + upload_id
    prefix = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"root\"\r\n\r\ngcodes\r\n"
              f"--{boundary}\r\nContent-Disposition: form-data; name=\"path\"\r\n\r\ncad-to-print\r\n"
              f"--{boundary}\r\nContent-Disposition: form-data; name=\"checksum\"\r\n\r\n{_sha256(source)}\r\n"
              f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{remote_name}\"\r\n"
              "Content-Type: application/octet-stream\r\n\r\n").encode("ascii")
    suffix = f"\r\n--{boundary}--\r\n".encode("ascii")
    result = _request("/server/files/upload", "POST", prefix + source.read_bytes() + suffix,
                      f"multipart/form-data; boundary={boundary}")
    item = result.get("item", {})
    remote_path = item.get("path")
    if not isinstance(remote_path, str) or not remote_path.startswith("cad-to-print/") or not remote_path.endswith(".gcode"):
        raise OrcaError(f"Upload response did not confirm the expected G-code path: {result}")
    folder = output_root() / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    record = {"upload_id": upload_id, "source": str(source), "sha256": _sha256(source),
              "remote_path": remote_path, "uploaded_utc": datetime.now(timezone.utc).isoformat(),
              "moonraker_url": _base_url()}
    (folder / f"{upload_id}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def start_print(upload_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
        raise OrcaError("upload_id must be the ID returned by upload_gcode")
    record_path = output_root() / "uploads" / f"{upload_id}.json"
    if not record_path.is_file():
        raise OrcaError("Unknown upload_id")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record["moonraker_url"] != _base_url():
        raise OrcaError("This upload belongs to a different Moonraker URL")
    if record.get("started_utc"):
        raise OrcaError("This upload has already been started")
    status = printer_status()
    if not status["klippy_connected"] or status["klippy_state"] != "ready":
        raise OrcaError("Printer is not ready")
    current = (status.get("print_stats") or {}).get("state")
    if current in ("printing", "paused"):
        raise OrcaError(f"Printer is already {current}")
    remote = record["remote_path"]
    query = urllib.parse.urlencode({"filename": remote})
    response = _request("/printer/print/start?" + query, "POST", b"")
    record["started_utc"] = datetime.now(timezone.utc).isoformat()
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {"upload_id": upload_id, "remote_path": remote, "response": response,
            "started_utc": record["started_utc"]}
