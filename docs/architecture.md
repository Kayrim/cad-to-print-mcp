# Architecture

The MCP server is an orchestrator. It does not implement geometry kernels, slicing, or printer firmware.

```text
MCP client (Codex or another agent)
           |
           v
cad-to-print-mcp (local stdio)
    |          |            |
    |          |            +--> Moonraker HTTP: status, upload, print start
    |          +---------------> OrcaSlicer CLI: presets, overrides, slice
    +--------------------------> FreeCADCmd: inspect FCStd, export STL
```

Each adapter is a separate Python module. FreeCAD's own Python runtime executes `freecad_worker.py` in a child process. The main MCP process never imports FreeCAD's binary modules, so it can use any supported Python 3.10+ environment. OrcaSlicer runs with an isolated `--datadir` per slice and writes a manifest plus logs. Moonraker upload and print start are separate state transitions.

## Current boundary

The OrcaSlicer CLI supports headless print settings and slicing. It does not expose the open GUI's plate, support painting, or interactive configuration. Live GUI control needs an upstream OrcaSlicer API or a compatible modified build; it belongs in another adapter rather than in the core workflow.

The first printer adapter targets Moonraker. Additional printer transports should implement status, upload, and print start with the same explicit state transitions. No remote address or credential is stored in source control.

## Next work

- Compare slice variants and produce structured estimates and warnings.
- Add a live OrcaSlicer adapter when the upstream control interface stabilizes.
- Add CAD exporters for OpenSCAD and other tools.
- Add printer adapters beyond Moonraker and a monitored print lifecycle.
- Add a packaged installer and CI tests on Windows, macOS, and Linux.
