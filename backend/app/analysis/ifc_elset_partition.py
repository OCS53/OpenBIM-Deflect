"""IFC 부재(GlobalId) ↔ CalculiX ELSET (MVP: 체적 요소 중심 vs 부재별 AABB).

병합 단일 체적 메쉬를 유지하고, 각 C3D4 의 무게중심이 어느 부재 축정렬 박스에 속하는지로 ELSET 을 나눈다.
인접·겹침 AABB 에서는 **박스 부피가 가장 작은** 부재를 택한다 (더 국소적일 가능성).
경계에 걸리면 ε 팽창 박스로 재판정 후, 그래도 없으면 첫 부재 ELSET.
"""

from __future__ import annotations

import hashlib
from typing import Sequence

from app.analysis.mesh_snapshot import MeshSnapshot

BBox6 = tuple[float, float, float, float, float, float]  # xmin, xmax, ymin, ymax, zmin, zmax


def elset_name_for_global_id(global_id: str) -> str:
    """CalculiX 안전 이름(영숫자+언더스코어, 길이 제한)."""
    raw = (global_id or "UNKNOWN").strip() or "UNKNOWN"
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14]
    return f"E_{h}"


def axis_aligned_bbox_from_verts(verts_flat: Sequence[float]) -> BBox6:
    """verts: [x0,y0,z0, ...]"""
    if len(verts_flat) < 3:
        raise ValueError("정점이 없습니다.")
    xs = verts_flat[0::3]
    ys = verts_flat[1::3]
    zs = verts_flat[2::3]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def _bbox_volume(b: BBox6) -> float:
    return max(b[1] - b[0], 1e-30) * max(b[3] - b[2], 1e-30) * max(b[5] - b[4], 1e-30)


def _expand_bbox(b: BBox6, eps: float) -> BBox6:
    return (
        b[0] - eps,
        b[1] + eps,
        b[2] - eps,
        b[3] + eps,
        b[4] - eps,
        b[5] + eps,
    )


def _point_in_bbox(x: float, y: float, z: float, b: BBox6) -> bool:
    return b[0] <= x <= b[1] and b[2] <= y <= b[3] and b[4] <= z <= b[5]


def assign_elsets_by_product_aabbs(
    snap: MeshSnapshot,
    products: Sequence[tuple[str, str, BBox6]],
) -> tuple[str, ...]:
    """
    products: (elset_name, global_id_ignored_here, bbox6) 부재 순서(첫 항목이 최종 폴백).
    """
    if not products:
        raise ValueError("IFC 부재 AABB 목록이 비어 있습니다.")

    node_by_tag = {n.tag: n for n in snap.nodes}
    eps_scale = _characteristic_length(snap)
    eps = max(eps_scale * 1.0e-6, 1e-9)
    expanded = [(ename, _expand_bbox(bb, eps)) for ename, _gid, bb in products]

    out: list[str] = []
    n_elem = len(snap.elem_tags)
    fallback = products[0][0]

    for e in range(n_elem):
        b = 4 * e
        n1 = snap.elem_nodes_flat[b]
        n2 = snap.elem_nodes_flat[b + 1]
        n3 = snap.elem_nodes_flat[b + 2]
        n4 = snap.elem_nodes_flat[b + 3]
        cx = cy = cz = 0.0
        for nid in (n1, n2, n3, n4):
            nd = node_by_tag[nid]
            cx += nd.x
            cy += nd.y
            cz += nd.z
        cx *= 0.25
        cy *= 0.25
        cz *= 0.25

        candidates: list[tuple[float, str]] = []
        for ename, bb in expanded:
            if _point_in_bbox(cx, cy, cz, bb):
                vol = _bbox_volume(bb)
                candidates.append((vol, ename))

        if not candidates:
            out.append(fallback)
        else:
            candidates.sort(key=lambda t: t[0])
            out.append(candidates[0][1])

    return tuple(out)


def _characteristic_length(snap: MeshSnapshot) -> float:
    xs = [n.x for n in snap.nodes]
    ys = [n.y for n in snap.nodes]
    zs = [n.z for n in snap.nodes]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    return max(dx, dy, dz, 1e-9)


def build_ifc_elset_map_json_rows(
    elem_elset: tuple[str, ...],
    products: Sequence[tuple[str, str, BBox6]],
) -> list[dict]:
    """sidecar 용: elset → global_id, 요소 개수."""
    elset_to_gid = {ename: gid for ename, gid, _bb in products}
    counts: dict[str, int] = {}
    for name in elem_elset:
        counts[name] = counts.get(name, 0) + 1
    rows: list[dict] = []
    for ename in sorted(counts.keys()):
        rows.append(
            {
                "elset": ename,
                "ifc_global_id": elset_to_gid.get(ename),
                "n_elements": counts[ename],
            }
        )
    return rows
