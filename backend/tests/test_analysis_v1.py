"""AnalysisInputV1 → resolve → CalculiX INP 텍스트 (단위)."""

from __future__ import annotations

import unittest

from app.analysis.ccx_emit import emit_ccx_static_inp
from app.analysis.load_spec_v1 import AnalysisInputV1
from app.analysis.mesh_snapshot import MeshNode, MeshSnapshot
from app.analysis.resolve_static_v1 import resolve_static_linear_v1


def _tiny_tet_snapshot() -> MeshSnapshot:
    """단일 C3D4: 노드 1~4 가 한 테트."""
    nodes = (
        MeshNode(1, 0.0, 0.0, 0.0),
        MeshNode(2, 1.0, 0.0, 0.0),
        MeshNode(3, 0.0, 1.0, 0.0),
        MeshNode(4, 0.0, 0.0, 1.0),
    )
    return MeshSnapshot(nodes=nodes, elem_tags=(1,), elem_nodes_flat=(1, 2, 3, 4))


def _spec_min_z_max_z_load() -> AnalysisInputV1:
    raw = {
        "version": 1,
        "analysis_type": "static_linear",
        "load_cases": [{"id": "LC1", "name": "t", "category": "GENERAL"}],
        "supports": [
            {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
        ],
        "loads": [
            {
                "type": "nodal_force",
                "id": "l1",
                "case_id": "LC1",
                "target": {"mode": "rule", "rule": "max_z_single_node"},
                "components": [0.0, 0.0, -5000.0],
            },
        ],
    }
    return AnalysisInputV1.model_validate(raw)


class ResolveEmitV1Tests(unittest.TestCase):
    def test_resolve_fixes_min_z_and_cload_max_z(self) -> None:
        snap = _tiny_tet_snapshot()
        spec = _spec_min_z_max_z_load()
        res = resolve_static_linear_v1(spec, snap)
        self.assertEqual(res.fix_node_ids, (1, 2, 3))
        self.assertEqual(res.boundary_dof_ranges, ((1, 3),))
        self.assertEqual(res.cloads, ((4, 3, -5000.0),))
        self.assertEqual(len(res.steps), 1)
        self.assertEqual(res.steps[0].case_id, "LC1")

    def test_emit_contains_boundary_and_cload(self) -> None:
        snap = _tiny_tet_snapshot()
        spec = _spec_min_z_max_z_load()
        res = resolve_static_linear_v1(spec, snap)
        text = emit_ccx_static_inp(snap, res, young_pa=210e9, poisson=0.3)
        self.assertIn("*BOUNDARY", text)
        self.assertIn("FIXBCMIN, 1, 3, 0.0", text)
        self.assertIn("*CLOAD", text)
        self.assertIn("4, 3,", text)
        self.assertEqual(text.count("\n*STEP\n"), 1)

    def test_two_load_cases_two_steps(self) -> None:
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [
                {"id": "LC1", "name": "dead", "category": "DEAD"},
                {"id": "LC2", "name": "wind", "category": "WIND"},
            ],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "nodal_force",
                    "id": "l1",
                    "case_id": "LC1",
                    "target": {"mode": "rule", "rule": "max_z_single_node"},
                    "components": [0.0, 0.0, -1000.0],
                },
                {
                    "type": "nodal_force",
                    "id": "l2",
                    "case_id": "LC2",
                    "target": {"mode": "rule", "rule": "max_z_single_node"},
                    "components": [500.0, 0.0, 0.0],
                },
            ],
        }
        spec = AnalysisInputV1.model_validate(raw)
        res = resolve_static_linear_v1(spec, snap)
        self.assertEqual(len(res.steps), 2)
        self.assertEqual(res.steps[0].cloads, ((4, 3, -1000.0),))
        self.assertEqual(res.steps[1].cloads, ((4, 1, 500.0),))
        text = emit_ccx_static_inp(snap, res, young_pa=210e9, poisson=0.3)
        self.assertEqual(text.count("\n*STEP\n"), 2)
        self.assertEqual(text.count("*END STEP"), 2)


if __name__ == "__main__":
    unittest.main()
