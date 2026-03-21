"""Gmsh 세션이 열린 상태에서 CalculiX .inp 기록 (레거시 bc 또는 AnalysisInputV1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gmsh

from app.analysis.ccx_emit import emit_ccx_static_inp
from app.analysis.load_spec_v1 import AnalysisInputV1
from app.analysis.mesh_snapshot import MeshSnapshot
from app.analysis.resolve_static_v1 import resolve_static_linear_v1

GMSH_TET4 = 4


def _legacy_write_ccx_inp_from_gmsh_mesh(
    inp_path: Path,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    bc_mode: str,
) -> None:
    """기존 스파이크 동작 (단일 CLOAD 휴리스틱)."""
    node_tags, coord, _ = gmsh.model.mesh.getNodes()
    if len(node_tags) == 0:
        raise RuntimeError("Gmsh: 노드가 없습니다.")

    tags_list = [int(t) for t in node_tags]
    coords = [float(c) for c in coord]
    n_nodes = len(tags_list)
    xs = coords[0::3]
    ys = coords[1::3]
    zs = coords[2::3]

    elem_types, elem_tags, node_tags_el = gmsh.model.mesh.getElements(dim=3)
    elem_out_tags: list[int] = []
    elem_out_nodes: list[int] = []
    for etype, tags, nodes in zip(elem_types, elem_tags, node_tags_el):
        if int(etype) != GMSH_TET4:
            continue
        n_elem = len(tags)
        for e in range(n_elem):
            elem_out_tags.append(int(tags[e]))
            base = 4 * e
            elem_out_nodes.extend(
                [
                    int(nodes[base]),
                    int(nodes[base + 1]),
                    int(nodes[base + 2]),
                    int(nodes[base + 3]),
                ]
            )
    if not elem_out_tags:
        raise RuntimeError("Gmsh: 3D 선형 사면체(TYPE 4)가 없습니다.")

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
    for i in range(n_nodes):
        nid = tags_list[i]
        lines.append(f"{nid:7d}, {xs[i]:.6e}, {ys[i]:.6e}, {zs[i]:.6e}")

    lines.append("*ELEMENT, TYPE=C3D4, ELSET=EALL")
    n_elem = len(elem_out_tags)
    for e in range(n_elem):
        tid = elem_out_tags[e]
        b = 4 * e
        n1, n2, n3, n4 = (
            elem_out_nodes[b],
            elem_out_nodes[b + 1],
            elem_out_nodes[b + 2],
            elem_out_nodes[b + 3],
        )
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
    lines.append("*SOLID SECTION, ELSET=EALL, MATERIAL=STEEL")
    lines.append("*STEP")
    lines.append("*STATIC")
    lines.append("*BOUNDARY")
    lines.append(f"{fix_set}, 1, 3, 0.0")
    lines.append("*CLOAD")
    lines.append(f"{load_node}, {load_dof}, {load_mag:.6e}")
    lines.append(f"*NODE FILE, NSET={all_set}")
    lines.append("U")
    lines.append("*EL FILE, ELSET=EALL")
    lines.append("S, NOE")
    lines.append(f"*NODE PRINT, NSET={all_set}")
    lines.append("U")
    lines.append("*END STEP")

    inp_path.parent.mkdir(parents=True, exist_ok=True)
    inp_path.write_text("\n".join(lines) + "\n", encoding="ascii")


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


def write_ccx_inp_from_gmsh_session(
    inp_path: Path,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    bc_mode: str,
    analysis_spec: dict[str, Any] | None,
    stats_out: dict[str, Any] | None = None,
) -> None:
    """
    Gmsh 체적 메쉬가 이미 생성된 세션에서 .inp 작성.
    analysis_spec 이 있으면 AnalysisInputV1 경로, 없으면 레거시 bc_mode.
    """
    if analysis_spec is not None:
        spec = AnalysisInputV1.model_validate(analysis_spec)
        snap = MeshSnapshot.from_gmsh_session(tet_element_type=GMSH_TET4)
        resolved = resolve_static_linear_v1(spec, snap)
        if stats_out is not None:
            stats_out["ccx_static_steps"] = len(resolved.steps)
            stats_out["ccx_step_case_ids"] = [s.case_id for s in resolved.steps]
        text = emit_ccx_static_inp(
            snap,
            resolved,
            young_pa=young_pa,
            poisson=poisson,
            heading="OpenBIM-Deflect C3D4 AnalysisInputV1",
        )
        inp_path.parent.mkdir(parents=True, exist_ok=True)
        inp_path.write_text(text, encoding="ascii")
        return

    _legacy_write_ccx_inp_from_gmsh_mesh(
        inp_path,
        young_pa=young_pa,
        poisson=poisson,
        point_load_n=point_load_n,
        bc_mode=bc_mode,
    )


def write_analysis_input_sidecar(out_dir: Path, spec: dict[str, Any]) -> None:
    """작업 폴더에 analysis_input.json 기록 (재현·디버그)."""
    p = out_dir / "analysis_input.json"
    p.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
