"""IFC ELSET 분할: AABB·중심 규칙."""

from __future__ import annotations

import unittest

from app.analysis.ifc_elset_partition import (
    assign_elsets_by_product_aabbs,
    axis_aligned_bbox_from_verts,
    build_ifc_elset_map_json_rows,
    elset_name_for_global_id,
)
from app.analysis.mesh_snapshot import MeshNode, MeshSnapshot


class IfcElsetPartitionTests(unittest.TestCase):
    def test_elset_name_stable(self) -> None:
        a = elset_name_for_global_id("abc")
        b = elset_name_for_global_id("abc")
        self.assertEqual(a, b)
        self.assertTrue(a.startswith("E_"))

    def test_centroid_inside_smaller_box_wins(self) -> None:
        """겹침 AABB 에서 부피가 작은 부재 ELSET 선택."""
        nodes = (
            MeshNode(1, 0.0, 0.0, 0.0),
            MeshNode(2, 1.0, 0.0, 0.0),
            MeshNode(3, 0.0, 1.0, 0.0),
            MeshNode(4, 0.0, 0.0, 1.0),
        )
        snap = MeshSnapshot(nodes=nodes, elem_tags=(100,), elem_nodes_flat=(1, 2, 3, 4))
        big = ("E_BIG", "gid-big", (-2.0, 2.0, -2.0, 2.0, -2.0, 2.0))
        small = ("E_SMALL", "gid-small", (0.0, 0.5, 0.0, 0.5, 0.0, 0.5))
        # tet centroid ~(0.25,0.25,0.25) in both; smaller volume should win
        out = assign_elsets_by_product_aabbs(snap, [big, small])
        self.assertEqual(out, ("E_SMALL",))

    def test_bbox_from_verts(self) -> None:
        bb = axis_aligned_bbox_from_verts((0.0, 0.0, 0.0, 2.0, 1.0, 3.0))
        self.assertEqual(bb, (0.0, 2.0, 0.0, 1.0, 0.0, 3.0))

    def test_map_json_rows(self) -> None:
        products = [
            ("E_A", "guid-a", (0.0, 1.0, 0.0, 1.0, 0.0, 1.0)),
            ("E_B", "guid-b", (2.0, 3.0, 0.0, 1.0, 0.0, 1.0)),
        ]
        elem_elset = ("E_A", "E_A", "E_B")
        rows = build_ifc_elset_map_json_rows(elem_elset, products)
        self.assertEqual(len(rows), 2)
        by_e = {r["elset"]: r for r in rows}
        self.assertEqual(by_e["E_A"]["n_elements"], 2)
        self.assertEqual(by_e["E_B"]["n_elements"], 1)


if __name__ == "__main__":
    unittest.main()
