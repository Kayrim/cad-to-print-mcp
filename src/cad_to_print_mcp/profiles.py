"""Discover and derive OrcaSlicer presets without editing the originals."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from .core import OrcaError, _existing_file, find_orca, output_root, profile_root


_KEY = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
_BLOCKED = re.compile(r"(?:gcode|script|post_process|password|token|api_key|print_host|authorization)", re.I)
_REDACTED = re.compile(r"(?:password|token|api_key|authorization|print_host)", re.I)


def _profile_file(path: str) -> Path:
    source = _existing_file(path, "profile", {".json"})
    roots = [profile_root(), profile_root().parent.parent / "system",
             output_root() / "profile-variants"]
    try:
        roots.append(find_orca().parent / "resources" / "profiles")
    except OrcaError:
        pass
    if not any(source.is_relative_to(root.resolve()) for root in roots):
        raise OrcaError("Profile must be inside OrcaSlicer's profile folders or the MCP variant folder")
    return source


def list_orca_profiles(kind: str, query: str = "", limit: int = 100) -> dict[str, Any]:
    if kind not in ("machine", "process", "filament"):
        raise OrcaError("kind must be machine, process, or filament")
    if not 1 <= limit <= 500:
        raise OrcaError("limit must be between 1 and 500")
    roots = [("user", profile_root() / kind)]
    try:
        roots.append(("bundled", find_orca().parent / "resources" / "profiles"))
    except OrcaError:
        pass
    needle = query.casefold()
    matches = []
    for origin, root in roots:
        if not root.is_dir():
            continue
        pattern = "*.json" if origin == "user" else f"*/{kind}/**/*.json"
        for path in sorted(root.glob(pattern)):
            if needle and needle not in path.stem.casefold():
                continue
            matches.append({"name": path.stem, "path": str(path.resolve()), "origin": origin})
            if len(matches) >= limit:
                return {"kind": kind, "query": query, "profiles": matches, "truncated": True}
    return {"kind": kind, "query": query, "profiles": matches, "truncated": False}


def read_orca_profile(path: str) -> dict[str, Any]:
    source = _profile_file(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrcaError(f"Invalid profile JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise OrcaError("Profile JSON must be an object")
    safe = {key: ("<redacted>" if _REDACTED.search(key) else value) for key, value in data.items()}
    return {"path": str(source), "settings": safe}


def _encode_value(key: str, value: Any) -> str | list[str]:
    if not _KEY.fullmatch(key) or _BLOCKED.search(key):
        raise OrcaError(f"Setting {key!r} cannot be edited through this tool")

    def scalar(item: Any) -> str:
        if isinstance(item, bool):
            return "1" if item else "0"
        if not isinstance(item, (str, int, float)):
            raise OrcaError(f"{key} must be text, number, boolean, or a list of those")
        result = str(item)
        if len(result) > 200 or any(ord(ch) < 32 for ch in result):
            raise OrcaError(f"{key} has an invalid or overly long value")
        return result

    if isinstance(value, list):
        if not 1 <= len(value) <= 16:
            raise OrcaError(f"{key} list must contain 1 to 16 values")
        return [scalar(item) for item in value]
    return scalar(value)


def derive_orca_profile(path: str, changes: dict[str, Any]) -> dict[str, Any]:
    source = _profile_file(path)
    if not isinstance(changes, dict) or not changes:
        raise OrcaError("changes must be a nonempty JSON object")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrcaError(f"Invalid profile JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("type") not in ("machine", "process", "filament"):
        raise OrcaError("This preset needs a type field; use a bundled OrcaSlicer profile")
    changed = {key: _encode_value(key, value) for key, value in changes.items()}
    data.update(changed)
    data["name"] = source.stem + " - MCP variant " + uuid.uuid4().hex[:8]
    data["from"] = "system"
    directory = output_root() / "profile-variants"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (uuid.uuid4().hex + ".json")
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"kind": data["type"], "source": str(source), "variant_path": str(target),
            "changes": changed, "original_unchanged": True}
