"""AnalysisInputV1 + MeshSnapshot → 고정 노드·케이스별 CLOAD (*STEP 단위)."""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.load_spec_v1 import (
    AnalysisInputV1,
    NodalForceLoadV1,
    NodalTargetExplicit,
    NodalTargetRule,
    SupportRuleV1,
)
from app.analysis.mesh_snapshot import MeshNode, MeshSnapshot


@dataclass(frozen=True)
class ResolvedStepV1:
    """CalculiX *STEP 하나에 대응 (동일 경계, 케이스별 하중)."""

    case_id: str
    case_name: str
    cloads: tuple[tuple[int, int, float], ...]


@dataclass(frozen=True)
class ResolvedStaticV1:
    fix_node_ids: tuple[int, ...]
    boundary_dof_ranges: tuple[tuple[int, int], ...]
    steps: tuple[ResolvedStepV1, ...]

    @property
    def cloads(self) -> tuple[tuple[int, int, float], ...]:
        """모든 스텝의 CLOAD 를 평탄화 (단일 스텝·테스트용)."""
        return tuple(x for s in self.steps for x in s.cloads)


def load_case_step_order_from_spec(spec: AnalysisInputV1) -> list[tuple[str, str]]:
    """INP 의 *STEP 순서와 동일한 (case_id, name) 목록 (하중이 있는 케이스만)."""
    return [
        (lc.id, lc.name)
        for lc in spec.load_cases
        if any(ld.case_id == lc.id for ld in spec.loads)
    ]


def _z_tol(zs: list[float]) -> float:
    zmin, zmax = min(zs), max(zs)
    return max((zmax - zmin) * 1.0e-6, 1e-9)


def _nodes_min_z(nodes: tuple[MeshNode, ...]) -> list[int]:
    zs = [n.z for n in nodes]
    tol = _z_tol(zs)
    zmin = min(zs)
    return [n.tag for n in nodes if n.z <= zmin + tol]


def _pick_single_max_z(nodes: tuple[MeshNode, ...]) -> int:
    best = max(nodes, key=lambda n: n.z)
    return best.tag


def _pick_single_min_z(nodes: tuple[MeshNode, ...]) -> int:
    best = min(nodes, key=lambda n: n.z)
    return best.tag


def _resolve_support_fix_tags(rules: list[SupportRuleV1], snap: MeshSnapshot) -> list[int]:
    tags: set[int] = set()
    for r in rules:
        if r.selection.type != "min_z":
            raise ValueError(f"지원하지 않는 support.selection: {r.selection.type}")
        for t in _nodes_min_z(snap.nodes):
            tags.add(t)
    if not tags:
        raise ValueError("고정 노드가 비어 있습니다.")
    return sorted(tags)


def _dof_ranges(fixed_dofs: list[int]) -> list[tuple[int, int]]:
    s = sorted({int(d) for d in fixed_dofs if 1 <= int(d) <= 6})
    if not s:
        raise ValueError("fixed_dofs 가 비어 있거나 범위 밖입니다.")
    ranges: list[tuple[int, int]] = []
    a = b = s[0]
    for x in s[1:]:
        if x == b + 1:
            b = x
        else:
            ranges.append((a, b))
            a = b = x
    ranges.append((a, b))
    return ranges


def _resolve_nodal_load(load: NodalForceLoadV1, snap: MeshSnapshot) -> list[tuple[int, int, float]]:
    out: list[tuple[int, int, float]] = []
    fx, fy, fz = load.components
    if isinstance(load.target, NodalTargetExplicit):
        targets = [int(x) for x in load.target.node_ids]
    elif isinstance(load.target, NodalTargetRule):
        if load.target.rule == "max_z_single_node":
            targets = [_pick_single_max_z(snap.nodes)]
        else:
            targets = [_pick_single_min_z(snap.nodes)]
    else:
        raise TypeError(type(load.target))

    for nid in targets:
        if fx != 0.0:
            out.append((nid, 1, float(fx)))
        if fy != 0.0:
            out.append((nid, 2, float(fy)))
        if fz != 0.0:
            out.append((nid, 3, float(fz)))
    return out


def resolve_static_linear_v1(spec: AnalysisInputV1, snap: MeshSnapshot) -> ResolvedStaticV1:
    fix_ids = _resolve_support_fix_tags(list(spec.supports), snap)
    dof_ranges = _dof_ranges(list(spec.supports[0].fixed_dofs))
    for s in spec.supports[1:]:
        if tuple(s.fixed_dofs) != tuple(spec.supports[0].fixed_dofs):
            raise ValueError("MVP: 모든 support 의 fixed_dofs 는 동일해야 합니다.")

    steps_out: list[ResolvedStepV1] = []
    for lc in spec.load_cases:
        chunk: list[tuple[int, int, float]] = []
        for ld in spec.loads:
            if ld.case_id == lc.id:
                chunk.extend(_resolve_nodal_load(ld, snap))
        if chunk:
            steps_out.append(
                ResolvedStepV1(
                    case_id=lc.id,
                    case_name=lc.name,
                    cloads=tuple(chunk),
                )
            )

    if not steps_out:
        raise ValueError("해석 가능한 CLOAD 가 없습니다 (components 가 모두 0?).")

    return ResolvedStaticV1(
        fix_node_ids=tuple(fix_ids),
        boundary_dof_ranges=tuple(dof_ranges),
        steps=tuple(steps_out),
    )
