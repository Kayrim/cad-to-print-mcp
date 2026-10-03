"""Compose CAD export and configured slicing into one traceable preparation step."""

from __future__ import annotations

from typing import Any

from .cad import export_stl
from .core import slice_model


def prepare_from_freecad(cad_path: str, object_name: str,
                         machine_profile: str, process_profile: str,
                         filament_profile: str, settings: dict[str, Any] | None = None,
                         timeout_seconds: int = 600) -> dict[str, Any]:
    """Export the selected solid, slice it, and return both records."""
    exported = export_stl(cad_path, object_name)
    sliced = slice_model(exported["stl_path"], settings, machine_profile,
                         process_profile, filament_profile, timeout_seconds)
    return {"cad_source": cad_path, "stl": exported, "slice": sliced,
            "ready_for_upload": sliced["status"] == "completed"}
