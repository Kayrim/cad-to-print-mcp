# CAD to Print MCP

A local MCP server that lets Codex and other MCP clients move a design through **FreeCAD → STL → OrcaSlicer configuration → G-code → Moonraker printer**. It uses stock OrcaSlicer's command-line interface and keeps every exported STL, derived preset, slice manifest, and G-code in a separate output location.

## What it does

- Inspect a FreeCAD `.FCStd` document and export a named solid to STL.
- Find, inspect, and derive OrcaSlicer machine, process, and filament presets. Derived presets are copies; originals stay untouched.
- Preview and run a slice with specified presets and settings. Each run records input hashes, command arguments, effective settings, logs, and output artifacts.
- Read G-code metadata, query a Moonraker printer, upload G-code, and start an uploaded print as a distinct step.

It does **not** edit the open OrcaSlicer GUI, paint supports, create CAD geometry from a text description, or control printers other than Moonraker yet. Agents can use their own CAD tools to create `.FCStd` files before using this server. OrcaSlicer itself is not bundled.

## Requirements

- Python 3.10 or newer
- FreeCAD with `FreeCADCmd` for `.FCStd` inspection/export
- OrcaSlicer with command-line mode
- Optional: a printer running Moonraker for status, upload, and print start

The server runs locally over MCP stdio. It does not open a listening port.

## Install

```powershell
git clone https://github.com/Kayrim/cad-to-print-mcp.git
cd cad-to-print-mcp
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

On macOS/Linux, use `python3 -m venv .venv` and `.venv/bin/python -m pip install -e .`.

Set these environment variables in your MCP client or shell:

| Variable | Purpose |
| --- | --- |
| `FREECAD_CMD_EXE` | Path to `freecadcmd.exe` or `FreeCADCmd` if it is not on `PATH` |
| `ORCA_SLICER_EXE` | Path to `orca-slicer.exe` or `orca-slicer` if auto-discovery fails |
| `ORCA_MCP_PROFILE_DIR` | Optional user profile directory override |
| `ORCA_MCP_OUTPUT_DIR` | Optional output directory; defaults to `~/OrcaSlicer-MCP/outputs` |
| `MOONRAKER_URL` | Moonraker URL, such as `http://printer.local:7125` |
| `MOONRAKER_API_KEY` | Optional Moonraker API key; never put it in a repository |

### Connect Codex

Use the Python executable from your new virtual environment. On Windows:

```powershell
codex mcp add cad-to-print -- "C:\absolute\path\to\cad-to-print-mcp\.venv\Scripts\python.exe" -m cad_to_print_mcp.server
codex mcp list
```

For other MCP clients, configure a local **stdio** server with the same executable and `-m cad_to_print_mcp.server` arguments. Restart the client after adding it.

## Example agent workflow

1. `check_setup` and `inspect_freecad_document` to choose the printable solid.
2. `export_freecad_stl` to create a mesh from the chosen FreeCAD object.
3. `find_profiles` for compatible machine, process, and filament presets. `read_profile` and `derive_profile` can make a variant with support, infill, speed, or other settings.
4. `preview_slice`, then `run_slice`. Or call `prepare_print_job` to export the selected FreeCAD object and slice it in one step. Review the manifest, logs, and generated G-code. The preset files should match the actual printer, nozzle, material, and firmware.
5. `get_printer_status`, then `upload_print_file`. Uploading alone never starts a print.
6. When ready, call `start_uploaded_print` using the returned upload ID. It refuses to start while the printer reports an active or paused job.

The `run_slice` tool accepts a `.3mf` with embedded settings or an STL/OBJ/STEP with all three preset JSON files. Common overrides such as `layer_height`, `enable_support`, `support_type`, `sparse_infill_density`, and `wall_loops` are directly validated. For other settings, derive a copy of a bundled preset and pass that copy to `run_slice`. OrcaSlicer validates the resulting configuration during slicing.

## Safety and privacy

- The server never runs shell commands assembled from tool inputs. It invokes FreeCAD and OrcaSlicer with argument arrays.
- It never edits original CAD files or OrcaSlicer presets.
- `derive_profile` refuses script, G-code, print host, and credential fields. `read_profile` redacts credentials.
- `upload_print_file` and `start_uploaded_print` are separate calls. Print start checks that Klipper is ready and no job is active.
- Generated files and manifests can contain model names and local paths. The `outputs/` directory is Git-ignored.
- Review G-code and printer preparation before starting a physical print. The server cannot check bed clearance, filament loading, or hardware condition.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests use local fixtures and mocked process/printer calls. A live smoke test should be run with your own FreeCAD, OrcaSlicer, presets, and Moonraker setup before printing. See `docs/architecture.md` for the adapter boundaries and roadmap.

## License

MIT. This project is independent of FreeCAD, OrcaSlicer, and Moonraker.
