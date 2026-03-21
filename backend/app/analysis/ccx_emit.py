"""MeshSnapshot + ResolvedStaticV1 → CalculiX .inp 텍스트 (정적 선형, 케이스별 *STEP)."""

from __future__ import annotations

from collections import defaultdict

from app.analysis.mesh_snapshot import MeshSnapshot
from app.analysis.resolve_static_v1 import ResolvedStaticV1


def _ccx_data_lines_ints(ids: list[int], *, max_per_line: int = 16) -> list[str]:
    rows: list[str] = []
    chunk: list[str] = []
    for x in ids:
        chunk.append(str(int(x)))
        if len(chunk) >= max_per_line:
            rows.append(",".join(chunk))
            chunk = []
    if chunk:
        rows.append(",".join(chunk))
    return rows


def _elements_grouped_by_elset(snap: MeshSnapshot) -> dict[str, list[tuple[int, int, int, int, int]]]:
    """elset_name → [(elem_tag, n1..n4), ...]"""
    n_elem = len(snap.elem_tags)
    d: dict[str, list[tuple[int, int, int, int, int]]] = defaultdict(list)
    for e in range(n_elem):
        ename = "EALL"
        if snap.elem_elset is not None:
            ename = snap.elem_elset[e]
        tid = snap.elem_tags[e]
        b = 4 * e
        d[ename].append(
            (
                tid,
                int(snap.elem_nodes_flat[b]),
                int(snap.elem_nodes_flat[b + 1]),
                int(snap.elem_nodes_flat[b + 2]),
                int(snap.elem_nodes_flat[b + 3]),
            )
        )
    return dict(d)


def emit_ccx_static_inp(
    snap: MeshSnapshot,
    res: ResolvedStaticV1,
    *,
    young_pa: float,
    poisson: float,
    heading: str = "OpenBIM-Deflect C3D4 AnalysisInputV1",
) -> str:
    tag_to_i = {n.tag: i for i, n in enumerate(snap.nodes)}
    lines: list[str] = ["*HEADING", heading, "*NODE"]
    for n in snap.nodes:
        lines.append(f"{n.tag:7d}, {n.x:.6e}, {n.y:.6e}, {n.z:.6e}")

    grouped = _elements_grouped_by_elset(snap)
    elset_order = sorted(grouped.keys())
    for ename in elset_order:
        lines.append(f"*ELEMENT, TYPE=C3D4, ELSET={ename}")
        for tid, n1, n2, n3, n4 in grouped[ename]:
            lines.append(f"{tid:7d}, {n1:7d}, {n2:7d}, {n3:7d}, {n4:7d}")

    fix_set = "FIXBCMIN"
    all_set = "NALL"
    all_ids = [n.tag for n in snap.nodes]
    lines.append(f"*NSET,NSET={fix_set}")
    lines.extend(_ccx_data_lines_ints(list(res.fix_node_ids)))
    lines.append(f"*NSET,NSET={all_set}")
    lines.extend(_ccx_data_lines_ints(all_ids))

    lines.append("*MATERIAL, NAME=STEEL")
    lines.append("*ELASTIC")
    lines.append(f" {young_pa:.6e}, {poisson:.3f}")
    for ename in elset_order:
        lines.append(f"*SOLID SECTION, ELSET={ename}, MATERIAL=STEEL")

    for si, step in enumerate(res.steps, start=1):
        label = step.case_id.replace("\n", " ").replace("\r", "")[:64]
        nm = (step.case_name or "").replace("\n", " ").replace("\r", "")[:64]
        lines.append(f"** STEP {si} load_case={label} name={nm}")
        lines.append("*STEP")
        lines.append("*STATIC")
        lines.append("*BOUNDARY")
        for a, b in res.boundary_dof_ranges:
            lines.append(f"{fix_set}, {a}, {b}, 0.0")
        lines.append("*CLOAD")
        for nid, dof, mag in step.cloads:
            if nid not in tag_to_i:
                raise ValueError(f"CLOAD 노드 {nid} 가 메쉬에 없습니다.")
            lines.append(f"{nid}, {dof}, {mag:.6e}")
        lines.append(f"*NODE FILE, NSET={all_set}")
        lines.append("U")
        for ename in elset_order:
            lines.append(f"*EL FILE, ELSET={ename}")
            lines.append("S, NOE")
        lines.append(f"*NODE PRINT, NSET={all_set}")
        lines.append("U")
        lines.append("*END STEP")

    return "\n".join(lines) + "\n"


def emit_legacy_point_load_inp(
    snap: MeshSnapshot,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    bc_mode: str,
) -> str:
    """레거시 boundary_mode + 단일 절점 CLOAD (스파이크)."""
    tags_list = [n.tag for n in snap.nodes]
    n_nodes = len(tags_list)
    xs = [n.x for n in snap.nodes]
    ys = [n.y for n in snap.nodes]
    zs = [n.z for n in snap.nodes]

    if bc_mode == "FIX_MIN_Y_LOAD_MAX_Y":
        fix_vals = ys
        load_pick = ys
        load_dof = 2
        load_scale = -1.0
    elif bc_mode == "FIX_MIN_Z_LOAD_TOP_X":
        fix_vals = zs
        load_pick = zs
        load_dof = 1
        load_scale = 1.0
    elif bc_mode == "FIX_MIN_Z_LOAD_TOP_Y":
        fix_vals = zs
        load_pick = zs
        load_dof = 2
        load_scale = 1.0
    else:
        fix_vals = zs
        load_pick = zs
        load_dof = 3
        load_scale = -1.0

    fv_min = min(fix_vals)
    fv_max = max(fix_vals)
    tol = max((fv_max - fv_min) * 1.0e-6, 1e-9)

    fix_nodes = [tags_list[i] for i in range(n_nodes) if fix_vals[i] <= fv_min + tol]
    if not fix_nodes:
        fix_nodes = [tags_list[fix_vals.index(fv_min)]]

    load_node = tags_list[max(range(n_nodes), key=lambda i: load_pick[i])]
    load_mag = load_scale * point_load_n

    lines: list[str] = [
        "*HEADING",
        f"OpenBIM-Deflect C3D4 bc={bc_mode} dof={load_dof}",
        "*NODE",
    ]
    for n in snap.nodes:
        lines.append(f"{n.tag:7d}, {n.x:.6e}, {n.y:.6e}, {n.z:.6e}")

    grouped = _elements_grouped_by_elset(snap)
    elset_order = sorted(grouped.keys())
    for ename in elset_order:
        lines.append(f"*ELEMENT, TYPE=C3D4, ELSET={ename}")
        for tid, n1, n2, n3, n4 in grouped[ename]:
            lines.append(f"{tid:7d}, {n1:7d}, {n2:7d}, {n3:7d}, {n4:7d}")

    fix_set = "FIXBCMIN"
    all_set = "NALL"
    lines.append(f"*NSET,NSET={fix_set}")
    lines.extend(_ccx_data_lines_ints(fix_nodes))
    lines.append(f"*NSET,NSET={all_set}")
    lines.extend(_ccx_data_lines_ints(tags_list))
    lines.append("*MATERIAL, NAME=STEEL")
    lines.append("*ELASTIC")
    lines.append(f" {young_pa:.6e}, {poisson:.3f}")
    for ename in elset_order:
        lines.append(f"*SOLID SECTION, ELSET={ename}, MATERIAL=STEEL")
    lines.append("*STEP")
    lines.append("*STATIC")
    lines.append("*BOUNDARY")
    lines.append(f"{fix_set}, 1, 3, 0.0")
    lines.append("*CLOAD")
    lines.append(f"{load_node}, {load_dof}, {load_mag:.6e}")
    lines.append(f"*NODE FILE, NSET={all_set}")
    lines.append("U")
    for ename in elset_order:
        lines.append(f"*EL FILE, ELSET={ename}")
        lines.append("S, NOE")
    lines.append(f"*NODE PRINT, NSET={all_set}")
    lines.append("U")
    lines.append("*END STEP")

    return "\n".join(lines) + "\n"
