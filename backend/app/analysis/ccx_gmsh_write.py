"""Gmsh 세션이 열린 상태에서 CalculiX .inp 기록 (레거시 bc 또는 AnalysisInputV1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import gmsh

from app.analysis.ccx_emit import emit_ccx_static_inp, emit_legacy_point_load_inp
from app.analysis.ifc_elset_partition import (
    assign_elsets_by_product_aabbs,
    build_ifc_elset_map_json_rows,
)
from app.analysis.load_spec_v1 import AnalysisInputV1
from app.analysis.mesh_snapshot import MeshSnapshot
from app.analysis.resolve_static_v1 import resolve_static_linear_v1

GMSH_TET4 = 4

IfcProductPartitionRow = tuple[str, str, tuple[float, float, float, float, float, float]]


def _snap_from_gmsh_with_optional_partition(
    ifc_product_partition: Sequence[IfcProductPartitionRow] | None,
) -> MeshSnapshot:
    snap0 = MeshSnapshot.from_gmsh_session(tet_element_type=GMSH_TET4)
    if not ifc_product_partition:
        return snap0
    ee = assign_elsets_by_product_aabbs(snap0, ifc_product_partition)
    return MeshSnapshot(
        nodes=snap0.nodes,
        elem_tags=snap0.elem_tags,
        elem_nodes_flat=snap0.elem_nodes_flat,
        elem_elset=ee,
    )


def _write_ifc_elset_sidecar(
    out_dir: Path,
    snap: MeshSnapshot,
    ifc_product_partition: Sequence[IfcProductPartitionRow],
) -> None:
    if snap.elem_elset is None:
        return
    rows = build_ifc_elset_map_json_rows(snap.elem_elset, ifc_product_partition)
    payload = {
        "version": 1,
        "method": "aabb_centroid",
        "notes": (
            "병합 체적 메쉬에서 사면체 무게중심이 IFC 부재별 AABB(ε 팽창)에 포함되면 해당 ELSET. "
            "겹침 시 가장 작은 AABB 부피 부재를 택함. 접촉면·공유 AABB 에서 오분류 가능."
        ),
        "products": rows,
    }
    (out_dir / "ifc_elset_map.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def write_ccx_inp_from_gmsh_session(
    inp_path: Path,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    bc_mode: str,
    analysis_spec: dict[str, Any] | None,
    stats_out: dict[str, Any] | None = None,
    ifc_product_partition: Sequence[IfcProductPartitionRow] | None = None,
    density_kg_m3: float = 7850.0,
) -> None:
    """
    Gmsh 체적 메쉬가 이미 생성된 세션에서 .inp 작성.
    ifc_product_partition: (elset_name, ifc_global_id, bbox6) 부재 목록 — 켜면 요소별 ELSET 분할 + sidecar.
    """
    snap = _snap_from_gmsh_with_optional_partition(ifc_product_partition)
    if stats_out is not None:
        stats_out["ifc_elset_partition"] = bool(ifc_product_partition)
        if ifc_product_partition and snap.elem_elset is not None:
            stats_out["ifc_elset_n_groups"] = len(set(snap.elem_elset))

    if ifc_product_partition:
        _write_ifc_elset_sidecar(inp_path.parent, snap, ifc_product_partition)

    if analysis_spec is not None:
        spec = AnalysisInputV1.model_validate(analysis_spec)
        resolved = resolve_static_linear_v1(
            spec, snap, default_density_kg_m3=float(density_kg_m3)
        )
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

    text = emit_legacy_point_load_inp(
        snap,
        young_pa=young_pa,
        poisson=poisson,
        point_load_n=point_load_n,
        bc_mode=bc_mode,
    )
    inp_path.parent.mkdir(parents=True, exist_ok=True)
    inp_path.write_text(text, encoding="ascii")


def write_analysis_input_sidecar(out_dir: Path, spec: dict[str, Any]) -> None:
    """작업 폴더에 analysis_input.json 기록 (재현·디버그)."""
    p = out_dir / "analysis_input.json"
    p.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
