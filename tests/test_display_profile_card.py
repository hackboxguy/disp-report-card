import json
import tempfile
import unittest
from pathlib import Path

from src.display_profile_card import BT709, BT2020, coverage, duv, key_values, main, D65

PROFILE = {
    "schema": "display-profile/1", "id": "test-b100-ldon", "created": "2026-10-28T00:00:00Z", "approximate": True,
    "display": {"model": "14.6-fhd-spartan7", "serial": "AAAA-BBBB-CCCCC", "type": "localdimming", "resolution": [1920, 1080]},
    "state": {"backlight_percent": 100, "local_dimming": "on", "panel_temp_c": 50.0, "warmup_min": 50,
              "signal_path": "pi4-dvp-8bit-bt709-limited", "player_code_offset": -0.5},
    "luminance": {"peak_nits_by_window_pct": {"3": 1400.0, "10": 1628.0, "100": 1428.0}, "white_xy": [0.2998, 0.3192],
                  "black_nits": {"full_screen": 0.0, "in_scene": 0.1185, "in_scene_source": "measured"}},
    "colour": {"primaries_xy": {"R": [0.68, 0.32], "G": [0.2735, 0.657], "B": [0.1386, 0.0577]}, "additivity_error_pct": 0.37},
    "tone_response": {"model_ramp": "ramp_window", "ramp_window_pct": 10.0,
                      "ramp_window": [[0, 0.0], [16, 3.3], [128, 360.0], [255, 1626.0]],
                      "ramp": [[0, 0.0], [16, 3.4], [128, 370.0], [255, 1450.0]]},
    "type_specific": {"localdimming": {}},
    "measurements": [{"kind": "sensor-location", "offset_mm": [1.2, -0.4], "footprint_px": 280}],
    "warnings": ["a warning that is long enough to need wrapping " * 4],
}


class ProfileCardTest(unittest.TestCase):
    def test_coverage(self) -> None:
        self.assertAlmostEqual(coverage(dict(BT709), BT709), 1.0)
        self.assertAlmostEqual(coverage(dict(BT2020), BT709), 1.0)   # BT.2020 contains BT.709
        self.assertLess(coverage(dict(BT709), BT2020), 0.6)
        self.assertIsNone(coverage({}, BT709))

    def test_duv(self) -> None:
        self.assertAlmostEqual(duv(D65, D65), 0.0)
        self.assertAlmostEqual(duv((0.2998, 0.3192), D65), 0.009, places=3)

    def test_key_values(self) -> None:
        text = "\n".join(key_values(PROFILE))
        self.assertIn("1,626 nits", text)
        self.assertIn("in scene 0.1185 nits (measured)", text)
        self.assertIn("footprint 280 px", text)

    def test_renders(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p, out = Path(d) / "p.json", Path(d) / "card.png"
            p.write_text(json.dumps(PROFILE))
            notes = Path(d) / "notes.txt"
            notes.write_text("assumed: in-scene black measured\n")
            self.assertEqual(main([f"--display-profile={p}", f"--output={out}", f"--notes-file={notes}"]), 0)
            self.assertGreater(out.stat().st_size, 50_000)

    def test_main_tool_dispatches(self) -> None:
        from src.display_report_card import main as card_main
        with tempfile.TemporaryDirectory() as d:
            p, out = Path(d) / "p.json", Path(d) / "card.png"
            p.write_text(json.dumps(PROFILE))
            self.assertEqual(card_main([f"--display-profile={p}", f"--output={out}"]), 0)
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
