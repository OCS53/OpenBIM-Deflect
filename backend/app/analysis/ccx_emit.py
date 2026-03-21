"""MeshSnapshot + ResolvedStaticV1 → CalculiX .inp 텍스트 (정적 선형, 케이스별 *STEP)."""

from __future__ import annotations

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

    lines.append("*ELEMENT, TYPE=C3D4, ELSET=EALL")
    n_elem = len(snap.elem_tags)
    for e in range(n_elem):
        tid = snap.elem_tags[e]
        b = 4 * e
        n1 = snap.elem_nodes_flat[b]
        n2 = snap.elem_nodes_flat[b + 1]
        n3 = snap.elem_nodes_flat[b + 2]
        n4 = snap.elem_nodes_flat[b + 3]
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
    lines.append("*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL")

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
        lines.append("*EL FILE, ELSET=EALL")
        lines.append("S, NOE")
        lines.append(f"*NODE PRINT, NSET={all_set}")
        lines.append("U")
        lines.append("*END STEP")

    return "\n".join(lines) + "\n"
