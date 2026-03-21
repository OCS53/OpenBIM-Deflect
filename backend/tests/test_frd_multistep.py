"""다중 DISP 블록 FRD → load_steps 파싱."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services.frd_extract import extract_frd_summary


class FrdMultistepTests(unittest.TestCase):
    def test_two_disp_blocks_yield_load_steps(self) -> None:
        body = """ -4  DISP        4    1
 -1      1  1.000000E+00  2.000000E+00  3.000000E+00
 -3
 -4  DISP        4    1
 -1      1  4.000000E+00  5.000000E+00  6.000000E+00
 -3
"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.frd"
            p.write_text(body, encoding="utf-8")
            summary = extract_frd_summary(
                p,
                step_labels=[("LC1", "a"), ("LC2", "b")],
            )
        self.assertIsNone(summary.get("parse_error"))
        steps = summary.get("load_steps")
        self.assertIsInstance(steps, list)
        assert isinstance(steps, list)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].get("case_id"), "LC1")
        self.assertEqual(steps[1].get("case_id"), "LC2")
        d0 = steps[0].get("displacement")
        d1 = steps[1].get("displacement")
        self.assertIsNotNone(d0)
        self.assertIsNotNone(d1)
        assert isinstance(d0, dict) and isinstance(d1, dict)
        self.assertEqual(d0["ux"][0], 1.0)
        self.assertEqual(d1["ux"][0], 4.0)
        root = summary.get("displacement")
        self.assertIsNotNone(root)
        assert isinstance(root, dict)
        self.assertEqual(root["ux"][0], 4.0)


if __name__ == "__main__":
    unittest.main()
