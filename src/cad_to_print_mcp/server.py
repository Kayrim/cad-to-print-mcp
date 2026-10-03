"""MCP tools exposed to Codex and other local MCP clients."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import __version__
from .cad import export_stl, find_freecad, inspect_cad
from .core import OrcaError, SETTINGS, find_orca, inspect_gcode, list_profiles, make_plan, slice_model
from .printer import printer_status, start_print, upload_gcode
from .profiles import derive_orca_profile, list_orca_profiles, read_orca_profile
from .workflow import prepare_from_freecad


mcp = MCPServer("cad-to-print-mcp", version=__version__)


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except OrcaError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def check_setup() -> dict[str, Any]:
    """Check local FreeCAD, OrcaSlicer and profile locations."""
    from .core import output_root, profile_root

    return {"freecad_executable": str(_call(find_freecad)),
            "orca_executable": str(_call(find_orca)), "profile_root": str(profile_root()),
            "output_root": str(output_root()), "server_version": __version__}


@mcp.tool()
def inspect_freecad_document(path: str) -> dict[str, Any]:
    """List solid objects, dimensions and validity from a FreeCAD .FCStd document."""
    return _call(inspect_cad, path)


@mcp.tool()
def export_freecad_stl(path: str, object_name: str) -> dict[str, Any]:
    """Export one selected FreeCAD object to STL without altering the CAD document."""
    return _call(export_stl, path, object_name)


@mcp.tool()
def list_supported_settings() -> dict[str, Any]:
    """List the validated print settings accepted by this server."""
    return {key: {"kind": spec.kind, "min": spec.low, "max": spec.high,
                  "choices": list(spec.choices)} for key, spec in SETTINGS.items()}


@mcp.tool()
def list_user_profiles() -> dict[str, Any]:
    """List local machine, process, and filament JSON presets available for slicing."""
    return list_profiles()


@mcp.tool()
def find_profiles(kind: str, query: str = "", limit: int = 100) -> dict[str, Any]:
    """Find bundled or user OrcaSlicer machine, process, or filament presets by name."""
    return _call(list_orca_profiles, kind, query, limit)


@mcp.tool()
def read_profile(path: str) -> dict[str, Any]:
    """Read a preset's settings, with credential fields redacted."""
    return _call(read_orca_profile, path)


@mcp.tool()
def derive_profile(path: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Create an isolated copy with new settings; original OrcaSlicer preset is unchanged."""
    return _call(derive_orca_profile, path, changes)


@mcp.tool()
def preview_slice(model: str, settings: dict[str, Any] | None = None,
                  machine_profile: str | None = None, process_profile: str | None = None,
                  filament_profile: str | None = None) -> dict[str, Any]:
    """Validate a slice request and show inputs, settings, and hashes without slicing."""
    return _call(make_plan, model, settings, machine_profile, process_profile, filament_profile)


@mcp.tool()
def run_slice(model: str, settings: dict[str, Any] | None = None,
              machine_profile: str | None = None, process_profile: str | None = None,
              filament_profile: str | None = None, timeout_seconds: int = 600) -> dict[str, Any]:
    """Slice with stock OrcaSlicer in a unique output folder; return artifacts and logs."""
    return _call(slice_model, model, settings, machine_profile, process_profile,
                 filament_profile, timeout_seconds)


@mcp.tool()
def prepare_print_job(cad_path: str, object_name: str, machine_profile: str,
                      process_profile: str, filament_profile: str,
                      settings: dict[str, Any] | None = None,
                      timeout_seconds: int = 600) -> dict[str, Any]:
    """Export one FreeCAD solid and slice it with explicit OrcaSlicer presets."""
    return _call(prepare_from_freecad, cad_path, object_name, machine_profile,
                 process_profile, filament_profile, settings, timeout_seconds)


@mcp.tool()
def read_gcode_summary(path: str) -> dict[str, Any]:
    """Read available print time, filament, and layer metadata from G-code or sliced 3MF."""
    return _call(inspect_gcode, path)


@mcp.tool()
def get_printer_status() -> dict[str, Any]:
    """Read Moonraker connection and current print state."""
    return _call(printer_status)


@mcp.tool()
def upload_print_file(path: str) -> dict[str, Any]:
    """Upload G-code to Moonraker without starting the printer; return an upload ID."""
    return _call(upload_gcode, path)


@mcp.tool()
def start_uploaded_print(upload_id: str) -> dict[str, Any]:
    """Start an uploaded G-code file after checking the printer is ready and idle."""
    return _call(start_print, upload_id)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
