"""AnalysisInputV1 → resolve → CalculiX INP 텍스트 (단위)."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.analysis.ccx_emit import emit_ccx_static_inp
from app.analysis.load_spec_v1 import AnalysisInputV1
from app.analysis.mesh_snapshot import MeshNode, MeshSnapshot
from app.analysis.resolve_static_v1 import load_case_step_order_from_spec, resolve_static_linear_v1


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

    def test_surface_pressure_exterior_resolves_to_nodal_cloads(self) -> None:
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [{"id": "LC1", "name": "pressure", "category": "WIND"}],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "surface_pressure",
                    "id": "p1",
                    "case_id": "LC1",
                    "magnitude": 1000.0,
                    "selection": {"kind": "exterior"},
                }
            ],
        }
        spec = AnalysisInputV1.model_validate(raw)
        res = resolve_static_linear_v1(spec, snap)
        self.assertEqual(len(res.steps), 1)
        self.assertGreater(len(res.steps[0].cloads), 0)
        # 폐곡면에 균일 압력을 주면 전체 합력은 0에 가깝다.
        sx = sum(m for _, dof, m in res.steps[0].cloads if dof == 1)
        sy = sum(m for _, dof, m in res.steps[0].cloads if dof == 2)
        sz = sum(m for _, dof, m in res.steps[0].cloads if dof == 3)
        self.assertAlmostEqual(sx, 0.0, places=8)
        self.assertAlmostEqual(sy, 0.0, places=8)
        self.assertAlmostEqual(sz, 0.0, places=8)

    def test_surface_pressure_facade_tilt_changes_cloads(self) -> None:
        snap = _tiny_tet_snapshot()
        base = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [{"id": "LC1", "name": "pressure", "category": "WIND"}],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [],
        }
        full_raw = {
            **base,
            "loads": [
                {
                    "type": "surface_pressure",
                    "id": "p1",
                    "case_id": "LC1",
                    "magnitude": 1000.0,
                    "selection": {"kind": "exterior"},
                }
            ],
        }
        tilt_raw = {
            **base,
            "loads": [
                {
                    "type": "surface_pressure",
                    "id": "p1",
                    "case_id": "LC1",
                    "magnitude": 1000.0,
                    "selection": {"kind": "exterior", "normal_max_tilt_deg": 25.0},
                }
            ],
        }
        res_full = resolve_static_linear_v1(AnalysisInputV1.model_validate(full_raw), snap)
        res_tilt = resolve_static_linear_v1(AnalysisInputV1.model_validate(tilt_raw), snap)
        # 면 수는 줄어도 (nid,dof) 병합으로 항목 개수가 같을 수 있음 → 분포는 달라야 함
        self.assertNotEqual(res_tilt.steps[0].cloads, res_full.steps[0].cloads)

    def test_load_combination_superposes_cloads(self) -> None:
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [
                {"id": "LC1", "name": "a", "category": "DEAD"},
                {"id": "LC2", "name": "b", "category": "LIVE"},
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
                    "components": [0.0, 0.0, -500.0],
                },
            ],
            "combinations": [
                {"id": "ULS", "name": "1.0D+1.0L", "factors": {"LC1": 1.0, "LC2": 1.0}},
            ],
        }
        spec = AnalysisInputV1.model_validate(raw)
        res = resolve_static_linear_v1(spec, snap)
        self.assertEqual(len(res.steps), 3)
        self.assertEqual(res.steps[2].case_id, "ULS")
        self.assertEqual(res.steps[2].cloads, ((4, 3, -1500.0),))
        order = load_case_step_order_from_spec(spec)
        self.assertEqual(
            order,
            [("LC1", "a"), ("LC2", "b"), ("ULS", "1.0D+1.0L")],
        )
        text = emit_ccx_static_inp(snap, res, young_pa=210e9, poisson=0.3)
        self.assertEqual(text.count("\n*STEP\n"), 3)

    def test_combination_schema_unknown_case_raises(self) -> None:
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [{"id": "LC1", "name": "a", "category": "G"}],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "nodal_force",
                    "id": "l1",
                    "case_id": "LC1",
                    "target": {"mode": "rule", "rule": "max_z_single_node"},
                    "components": [0.0, 0.0, -1.0],
                },
            ],
            "combinations": [{"id": "C1", "name": "", "factors": {"LC9": 1.0}}],
        }
        with self.assertRaises(ValidationError):
            AnalysisInputV1.model_validate(raw)

    @patch("app.analysis.resolve_static_v1._boundary_faces_with_outward_normals")
    def test_surface_pressure_facade_tilt_no_face_raises(self, mock_faces) -> None:
        mock_faces.return_value = [
            ((1, 2, 3), (0.0, 0.0, 1.0), 1.0),
        ]
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [{"id": "LC1", "name": "pressure", "category": "WIND"}],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "surface_pressure",
                    "id": "p1",
                    "case_id": "LC1",
                    "magnitude": 1000.0,
                    "selection": {"kind": "exterior", "normal_max_tilt_deg": 30.0},
                }
            ],
        }
        spec = AnalysisInputV1.model_validate(raw)
        with self.assertRaises(ValueError) as ctx:
            resolve_static_linear_v1(spec, snap)
        self.assertIn("외곽면이 없습니다", str(ctx.exception))

    def test_gravity_resolves_to_lumped_z_cloads(self) -> None:
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [{"id": "LC_G", "name": "dead", "category": "DEAD"}],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "gravity",
                    "id": "g1",
                    "case_id": "LC_G",
                    "acceleration": [0.0, 0.0, -1.0],
                },
            ],
            "material_density_kg_m3": 24.0,
        }
        spec = AnalysisInputV1.model_validate(raw)
        res = resolve_static_linear_v1(spec, snap, default_density_kg_m3=1.0)
        # V=1/6 m³, rho=24, az=-1 → Fz_total = -4 N, 각 노드 -1 N (dof 3)
        self.assertEqual(len(res.steps), 1)
        fz = [m for nid, dof, m in res.steps[0].cloads if dof == 3]
        self.assertEqual(len(fz), 4)
        self.assertAlmostEqual(sum(fz), -4.0, places=10)
        for v in fz:
            self.assertAlmostEqual(v, -1.0, places=10)

    def test_gravity_zero_acceleration_raises(self) -> None:
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [{"id": "LC1", "name": "a", "category": "G"}],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "gravity",
                    "id": "g1",
                    "case_id": "LC1",
                    "acceleration": [0.0, 0.0, 0.0],
                },
            ],
        }
        spec = AnalysisInputV1.model_validate(raw)
        with self.assertRaises(ValueError) as ctx:
            resolve_static_linear_v1(spec, snap)
        self.assertIn("acceleration", str(ctx.exception))

    def test_combination_includes_gravity_case(self) -> None:
        snap = _tiny_tet_snapshot()
        raw = {
            "version": 1,
            "analysis_type": "static_linear",
            "load_cases": [
                {"id": "LC1", "name": "a", "category": "DEAD"},
                {"id": "LC2", "name": "b", "category": "LIVE"},
            ],
            "supports": [
                {"id": "s1", "selection": {"type": "min_z"}, "fixed_dofs": [1, 2, 3]},
            ],
            "loads": [
                {
                    "type": "gravity",
                    "id": "g1",
                    "case_id": "LC1",
                    "acceleration": [0.0, 0.0, -1.0],
                },
                {
                    "type": "nodal_force",
                    "id": "n1",
                    "case_id": "LC2",
                    "target": {"mode": "rule", "rule": "max_z_single_node"},
                    "components": [0.0, 0.0, -100.0],
                },
            ],
            "material_density_kg_m3": 24.0,
            "combinations": [{"id": "C1", "name": "", "factors": {"LC1": 1.0, "LC2": 1.0}}],
        }
        spec = AnalysisInputV1.model_validate(raw)
        res = resolve_static_linear_v1(spec, snap)
        self.assertEqual(len(res.steps), 3)
        # LC1 중력: 4노드 각 Fz=-1; LC2 노드력: 노드 4 에 Fz=-100
        # C1: 노드 4 만 -101, 나머지 -1
        c1 = next(s for s in res.steps if s.case_id == "C1")
        self.assertEqual(
            c1.cloads,
            ((1, 3, -1.0), (2, 3, -1.0), (3, 3, -1.0), (4, 3, -101.0)),
        )


if __name__ == "__main__":
    unittest.main()
