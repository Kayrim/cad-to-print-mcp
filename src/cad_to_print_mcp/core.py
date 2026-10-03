"""Validated, isolated OrcaSlicer command-line operations."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class OrcaError(ValueError):
    """A user-correctable OrcaSlicer operation error."""


@dataclass(frozen=True)
class Setting:
    kind: str
    low: float | None = None
    high: float | None = None
    choices: tuple[str, ...] = ()


# Explicit settings keep command execution predictable. Expand only with documented Orca keys.
SETTINGS: dict[str, Setting] = {
    "layer_height": Setting("number", 0.04, 1.0),
    "initial_layer_print_height": Setting("number", 0.04, 1.0),
    "enable_support": Setting("bool"),
    "support_type": Setting("choice", choices=("normal(auto)", "tree(auto)", "normal(manual)", "tree(manual)")),
    "support_style": Setting("choice", choices=("default", "grid", "snug", "organic", "tree_slim", "tree_strong", "tree_hybrid")),
    "support_threshold_angle": Setting("integer", 0, 90),
    "support_on_build_plate_only": Setting("bool"),
    "support_critical_regions_only": Setting("bool"),
    "sparse_infill_density": Setting("percent", 0, 100),
    "sparse_infill_pattern": Setting("choice", choices=("rectilinear", "grid", "cubic", "gyroid", "honeycomb", "lightning", "concentric", "triangles")),
    "wall_loops": Setting("integer", 1, 20),
    "top_shell_layers": Setting("integer", 0, 30),
    "bottom_shell_layers": Setting("integer", 0, 30),
    "brim_type": Setting("choice", choices=("auto_brim", "outer_only", "inner_only", "outer_and_inner", "no_brim")),
    "brim_width": Setting("number", 0, 50),
}

MODEL_SUFFIXES = {".3mf", ".stl", ".obj", ".step", ".stp"}
PROFILE_KINDS = ("machine", "process", "filament")
MAX_LOG_CHARS = 12000


def _existing_file(value: str, label: str, suffixes: set[str] | None = None) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise OrcaError(f"{label} does not exist: {path}")
    if suffixes and path.suffix.lower() not in suffixes:
        raise OrcaError(f"{label} must have one of these extensions: {', '.join(sorted(suffixes))}")
    return path


def find_orca() -> Path:
    configured = os.environ.get("ORCA_SLICER_EXE")
    if configured:
        return _existing_file(configured, "ORCA_SLICER_EXE")
    found = shutil.which("orca-slicer") or shutil.which("orca-slicer.exe")
    candidates = [found] if found else []
    if sys.platform == "win32":
        candidates += [
            str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "OrcaSlicer" / "orca-slicer.exe"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "OrcaSlicer" / "orca-slicer.exe"),
        ]
    elif sys.platform == "darwin":
        candidates += ["/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise OrcaError("OrcaSlicer CLI was not found. Set ORCA_SLICER_EXE to its executable path.")


def output_root() -> Path:
    value = os.environ.get("ORCA_MCP_OUTPUT_DIR")
    return Path(value).expanduser().resolve() if value else (Path.home() / "OrcaSlicer-MCP" / "outputs").resolve()


def profile_root() -> Path:
    value = os.environ.get("ORCA_MCP_PROFILE_DIR")
    if value:
        return Path(value).expanduser().resolve()
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "OrcaSlicer" / "user" / "default"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OrcaSlicer" / "user" / "default"
    return Path.home() / ".config" / "OrcaSlicer" / "user" / "default"


def list_profiles() -> dict[str, Any]:
    root = profile_root()
    profiles: dict[str, list[dict[str, str]]] = {}
    for kind in PROFILE_KINDS:
        directory = root / kind
        profiles[kind] = [
            {"name": p.stem, "path": str(p.resolve())}
            for p in sorted(directory.glob("*.json")) if p.is_file()
        ] if directory.is_dir() else []
    return {"profile_root": str(root), "profiles": profiles}


def normalize_settings(values: dict[str, Any] | None) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise OrcaError("settings must be a JSON object")
    normalized: dict[str, str] = {}
    for key, raw in sorted(values.items()):
        spec = SETTINGS.get(key)
        if spec is None:
            raise OrcaError(f"Unsupported setting {key!r}. Use list_settings to see accepted keys.")
        if spec.kind == "bool":
            if type(raw) is not bool:
                raise OrcaError(f"{key} must be true or false")
            normalized[key] = "1" if raw else "0"
        elif spec.kind == "choice":
            if not isinstance(raw, str) or raw not in spec.choices:
                raise OrcaError(f"{key} must be one of: {', '.join(spec.choices)}")
            normalized[key] = raw
        else:
            if type(raw) not in (int, float) or not math.isfinite(raw):
                raise OrcaError(f"{key} must be a finite number")
            if spec.kind == "integer" and type(raw) is not int:
                raise OrcaError(f"{key} must be an integer")
            if spec.low is not None and raw < spec.low or spec.high is not None and raw > spec.high:
                raise OrcaError(f"{key} must be between {spec.low} and {spec.high}")
            normalized[key] = f"{raw:g}" + ("%" if spec.kind == "percent" else "")
    return normalized


def _profiles(machine: str | None, process: str | None, filament: str | None) -> dict[str, Path]:
    selected: dict[str, Path] = {}
    for kind, value in (("machine", machine), ("process", process), ("filament", filament)):
        if value:
            selected[kind] = _existing_file(value, f"{kind} profile", {".json"})
    return selected


def make_plan(model: str, settings: dict[str, Any] | None = None,
              machine_profile: str | None = None, process_profile: str | None = None,
              filament_profile: str | None = None) -> dict[str, Any]:
    source = _existing_file(model, "model", MODEL_SUFFIXES)
    selected = _profiles(machine_profile, process_profile, filament_profile)
    if source.suffix.lower() != ".3mf" and set(selected) != set(PROFILE_KINDS):
        raise OrcaError("STL/OBJ/STEP slicing needs machine, process, and filament JSON profiles. A 3MF may carry its own settings.")
    normalized = normalize_settings(settings)
    return {
        "model": str(source),
        "model_sha256": _sha256(source),
        "profiles": {key: {"path": str(path), "sha256": _sha256(path)} for key, path in selected.items()},
        "settings": normalized,
        "orca_executable": str(find_orca()),
        "output_root": str(output_root()),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command(plan: dict[str, Any], directory: Path) -> list[str]:
    args = [plan["orca_executable"], plan["model"], "--datadir", str(directory / "config"),
            "--outputdir", str(directory), "--slice", "0", "--export-settings", str(directory / "effective-settings.json")]
    profiles = plan["profiles"]
    if "machine" in profiles or "process" in profiles:
        paths = [profiles[kind]["path"] for kind in ("process", "machine") if kind in profiles]
        args += ["--load-settings", ";".join(paths)]
    if "filament" in profiles:
        args += ["--load-filaments", profiles["filament"]["path"]]
    args += [f"--{key.replace('_', '-')}={value}" for key, value in plan["settings"].items()]
    return args


def slice_model(model: str, settings: dict[str, Any] | None = None,
                machine_profile: str | None = None, process_profile: str | None = None,
                filament_profile: str | None = None, timeout_seconds: int = 600) -> dict[str, Any]:
    if type(timeout_seconds) is not int or not 30 <= timeout_seconds <= 3600:
        raise OrcaError("timeout_seconds must be an integer from 30 to 3600")
    plan = make_plan(model, settings, machine_profile, process_profile, filament_profile)
    root = Path(plan["output_root"])
    root.mkdir(parents=True, exist_ok=True)
    directory = root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    directory.mkdir()
    command = _command(plan, directory)
    manifest_path = directory / "manifest.json"
    manifest = {"status": "running", "created_utc": datetime.now(timezone.utc).isoformat(), "plan": plan, "command": command}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    try:
        completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, errors="replace", timeout=timeout_seconds,
                                   cwd=directory, shell=False)
        stdout, stderr = completed.stdout, completed.stderr
        code = completed.returncode
        status = "completed" if code == 0 else "failed"
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        code, status = None, "timed_out"
    except OSError as exc:
        stdout, stderr, code, status = "", str(exc), None, "failed"
    (directory / "stdout.log").write_text(stdout, encoding="utf-8")
    (directory / "stderr.log").write_text(stderr, encoding="utf-8")
    artifacts = sorted(str(p) for p in directory.iterdir() if p.is_file() and p.suffix.lower() in {".gcode", ".3mf"})
    diagnostics = list(dict.fromkeys(line.strip() for line in (stdout + "\n" + stderr).splitlines()
                                    if re.match(r"\s*(?:warning|error):", line, re.I)))[:20]
    if status == "completed" and not artifacts:
        status = "failed"
        stderr += "\nOrcaSlicer exited successfully but produced no G-code or 3MF artifact."
    elif status == "completed" and diagnostics:
        status = "completed_with_warnings"
    manifest.update({"status": status, "return_code": code, "artifacts": artifacts,
                     "diagnostics": diagnostics,
                     "completed_utc": datetime.now(timezone.utc).isoformat()})
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"status": status, "return_code": code, "output_directory": str(directory),
            "artifacts": artifacts, "diagnostics": diagnostics, "manifest": str(manifest_path),
            "stdout_tail": stdout[-MAX_LOG_CHARS:], "stderr_tail": stderr[-MAX_LOG_CHARS:]}


def inspect_gcode(path: str) -> dict[str, Any]:
    source = _existing_file(path, "G-code", {".gcode", ".3mf"})
    if source.suffix.lower() == ".3mf":
        with zipfile.ZipFile(source) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".gcode")]
            if not names:
                raise OrcaError("No G-code member found in 3MF archive")
            with archive.open(names[0]) as stream:
                head = stream.read(256 * 1024)
                stream.seek(max(0, archive.getinfo(names[0]).file_size - 2 * 1024 * 1024))
                tail = stream.read(2 * 1024 * 1024)
    else:
        with source.open("rb") as stream:
            head = stream.read(256 * 1024)
            stream.seek(max(0, source.stat().st_size - 2 * 1024 * 1024))
            tail = stream.read(2 * 1024 * 1024)
    data = (head + b"\n" + tail).decode("utf-8", "replace")
    metadata: dict[str, str] = {}
    patterns = {
        "estimated_printing_time": r"(?im)^;\s*estimated printing time[^=]*=\s*(.+)$",
        "filament_used_g": r"(?im)^;\s*filament used \[g\]\s*=\s*(.+)$",
        "filament_used_mm": r"(?im)^;\s*filament used \[mm\]\s*=\s*(.+)$",
        "layer_height": r"(?im)^;\s*layer_height\s*=\s*(.+)$",
        "total_layers": r"(?im)^;\s*total layer number\s*:\s*(.+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, data)
        if match:
            metadata[key] = match.group(1).strip()
    return {"path": str(source), "sha256": _sha256(source), "size_bytes": source.stat().st_size,
            "metadata": metadata, "note": "Metadata is reported only when present in the G-code header."}
