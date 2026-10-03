import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp import Client

from cad_to_print_mcp.core import OrcaError
from cad_to_print_mcp.printer import start_print, upload_gcode
from cad_to_print_mcp.profiles import derive_orca_profile, read_orca_profile
from cad_to_print_mcp.server import mcp


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "process.json"
        self.profile.write_text(json.dumps({"type": "process", "name": "base",
                                            "layer_height": "0.2", "machine_start_gcode": "G28"}),
                                encoding="utf-8")

    def test_derive_preserves_original_and_redacts(self):
        with patch.dict(os.environ, {"ORCA_MCP_OUTPUT_DIR": str(self.root / "out"),
                                     "ORCA_MCP_PROFILE_DIR": str(self.root)}):
            result = derive_orca_profile(str(self.profile), {"layer_height": 0.16,
                                                              "enable_support": True})
            read = read_orca_profile(str(self.profile))
        derived = json.loads(Path(result["variant_path"]).read_text(encoding="utf-8"))
        original = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertEqual(derived["layer_height"], "0.16")
        self.assertEqual(derived["enable_support"], "1")
        self.assertEqual(original["layer_height"], "0.2")
        self.assertEqual(read["settings"]["machine_start_gcode"], "G28")

    def test_blocks_script_changes(self):
        with patch.dict(os.environ, {"ORCA_MCP_PROFILE_DIR": str(self.root)}):
            with self.assertRaises(OrcaError):
                derive_orca_profile(str(self.profile), {"machine_start_gcode": "M112"})


class PrinterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"ORCA_MCP_OUTPUT_DIR": str(self.root / "out"),
                                        "MOONRAKER_URL": "http://printer.local:7125"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_upload_and_busy_preflight(self):
        gcode = self.root / "sample.gcode"
        gcode.write_text("G28\n", encoding="utf-8")
        with patch("cad_to_print_mcp.printer._request", return_value={
            "item": {"path": "cad-to-print/sample-12345678.gcode"}}) as request:
            uploaded = upload_gcode(str(gcode))
        self.assertEqual(uploaded["remote_path"], "cad-to-print/sample-12345678.gcode")
        self.assertIn("multipart/form-data", request.call_args.args[3])
        with patch("cad_to_print_mcp.printer.printer_status", return_value={
            "klippy_connected": True, "klippy_state": "ready", "print_stats": {"state": "printing"}}):
            with self.assertRaisesRegex(OrcaError, "already printing"):
                start_print(uploaded["upload_id"])


class McpTests(unittest.TestCase):
    def test_tools_discoverable(self):
        async def check():
            async with Client(mcp) as client:
                result = await client.list_tools()
                names = {tool.name for tool in result.tools}
                self.assertTrue({"inspect_freecad_document", "derive_profile", "prepare_print_job", "run_slice",
                                 "upload_print_file", "start_uploaded_print"} <= names)
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
