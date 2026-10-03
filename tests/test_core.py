import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cad_to_print_mcp.core import OrcaError, _command, inspect_gcode, make_plan, normalize_settings, slice_model


class SettingsTests(unittest.TestCase):
    def test_common_settings(self):
        self.assertEqual(normalize_settings({"layer_height": 0.2, "enable_support": True,
                                             "sparse_infill_density": 20}),
                         {"enable_support": "1", "layer_height": "0.2", "sparse_infill_density": "20%"})

    def test_rejects_unsafe_or_invalid_values(self):
        for item in ({"machine_start_gcode": "M112"}, {"layer_height": 5},
                     {"enable_support": "yes"}, {"sparse_infill_density": float("nan")},
                     {"wall_loops": True}):
            with self.subTest(item=item), self.assertRaises(OrcaError):
                normalize_settings(item)


class SliceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / "part.3mf"
        self.model.write_bytes(b"test model")
        self.exe = self.root / "orca-slicer.exe"
        self.exe.write_bytes(b"stub")

    def test_preview_and_command(self):
        with patch.dict(os.environ, {"ORCA_SLICER_EXE": str(self.exe),
                                     "ORCA_MCP_OUTPUT_DIR": str(self.root / "out")}):
            plan = make_plan(str(self.model), {"layer_height": 0.2, "enable_support": True})
        args = _command(plan, self.root / "job")
        self.assertIn("--layer-height=0.2", args)
        self.assertIn("--enable-support=1", args)
        self.assertIn("--datadir", args)
        self.assertEqual(plan["model_sha256"], hashlib.sha256(b"test model").hexdigest())

    def test_stl_needs_profiles(self):
        stl = self.root / "part.stl"
        stl.write_bytes(b"solid test")
        with self.assertRaisesRegex(OrcaError, "needs machine"):
            make_plan(str(stl))

    def test_slice_records_failure(self):
        with patch.dict(os.environ, {"ORCA_SLICER_EXE": str(self.exe),
                                     "ORCA_MCP_OUTPUT_DIR": str(self.root / "out")}), \
             patch("cad_to_print_mcp.core.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            run.return_value.stderr = "invalid profile"
            result = slice_model(str(self.model))
        self.assertEqual(result["status"], "failed")
        manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["return_code"], 1)
        self.assertTrue((Path(result["output_directory"]) / "stderr.log").is_file())

    def test_gcode_summary(self):
        source = self.root / "part.gcode"
        source.write_text("; estimated printing time (normal mode) = 1h 20m\n; filament used [g] = 23.4\n",
                          encoding="utf-8")
        metadata = inspect_gcode(str(source))["metadata"]
        self.assertEqual(metadata["estimated_printing_time"], "1h 20m")
        self.assertEqual(metadata["filament_used_g"], "23.4")


if __name__ == "__main__":
    unittest.main()
