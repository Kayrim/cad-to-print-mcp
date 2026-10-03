"""FreeCAD document inspection and STL export."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .core import OrcaError, _existing_file, output_root


def find_freecad() -> Path:
    configured = os.environ.get("FREECAD_CMD_EXE")
    if configured:
        return _existing_file(configured, "FREECAD_CMD_EXE")
    found = shutil.which("freecadcmd") or shutil.which("FreeCADCmd.exe")
    candidates = [found] if found else []
    if sys.platform == "win32":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        candidates.extend(str(path) for path in program_files.glob("FreeCAD*/bin/freecadcmd.exe"))
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value).resolve()
    raise OrcaError("FreeCADCmd was not found. Set FREECAD_CMD_EXE to its executable path.")


def _run_worker(source: str, action: str, object_name: str | None = None,
                target: Path | None = None) -> dict[str, Any]:
    cad = _existing_file(source, "CAD document", {".fcstd"})
    worker = Path(__file__).with_name("freecad_worker.py")
    with tempfile.TemporaryDirectory(prefix="cad-to-print-") as temporary:
        result_path = Path(temporary) / "result.json"
        env = os.environ.copy()
        env.update({"CAD_MCP_SOURCE": str(cad), "CAD_MCP_ACTION": action,
                    "CAD_MCP_RESULT": str(result_path), "CAD_MCP_OBJECT": object_name or "",
                    "CAD_MCP_TARGET": str(target) if target else ""})
        try:
            completed = subprocess.run([str(find_freecad()), str(worker)], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                       errors="replace", timeout=120, env=env, cwd=temporary, shell=False)
        except subprocess.TimeoutExpired as exc:
            raise OrcaError("FreeCAD took longer than 120 seconds") from exc
        if not result_path.is_file():
            raise OrcaError("FreeCAD did not produce a result. " + completed.stderr[-2000:])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if completed.returncode != 0 or not result.get("ok"):
            raise OrcaError("FreeCAD export failed: " + result.get("error", completed.stderr)[-4000:])
        return result["result"]


def inspect_cad(source: str) -> dict[str, Any]:
    """Return named solid objects so the agent can choose an export target."""
    return _run_worker(source, "inspect")


def export_stl(source: str, object_name: str) -> dict[str, Any]:
    if not object_name or len(object_name) > 200:
        raise OrcaError("object_name must name one FreeCAD object")
    root = output_root() / "cad-exports"
    root.mkdir(parents=True, exist_ok=True)
    target = root / (Path(source).stem + "-" + uuid.uuid4().hex[:10] + ".stl")
    result = _run_worker(source, "export", object_name, target)
    if not target.is_file() or target.stat().st_size == 0:
        raise OrcaError("FreeCAD reported success but STL output is missing or empty")
    return result["exported"]
