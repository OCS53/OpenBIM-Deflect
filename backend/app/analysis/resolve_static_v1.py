"""AnalysisInputV1 + MeshSnapshot → 고정 노드·케이스별 CLOAD (*STEP 단위)."""

from __future__ import annotations

from dataclasses import dataclass
import math

from app.analysis.load_spec_v1 import (
    AnalysisInputV1,
    GravityLoadV1,
    NodalForceLoadV1,
    NodalTargetExplicit,
    NodalTargetRule,
    SurfacePressureLoadV1,
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
    """INP 의 *STEP 순서와 동일한 (case_id, name) 목록 (하중 케이스 + 조합 순)."""
    primary = [
        (lc.id, lc.name)
        for lc in spec.load_cases
        if any(ld.case_id == lc.id for ld in spec.loads)
    ]
    combo = [(c.id, c.name) for c in spec.combinations]
    return primary + combo


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


def _boundary_faces_with_outward_normals(
    snap: MeshSnapshot,
) -> list[tuple[tuple[int, int, int], tuple[float, float, float], float]]:
    """
    C3D4 외곽 삼각면 추출.
    반환: (삼각면 노드 3개, 외향 단위법선, 면적)
    """
    node_xyz = {n.tag: (n.x, n.y, n.z) for n in snap.nodes}
    # key=정렬 face 노드, value=(원래 순서 tri, 해당 테트 중심)
    faces: dict[tuple[int, int, int], list[tuple[tuple[int, int, int], tuple[float, float, float]]]] = {}
    for e in range(len(snap.elem_tags)):
        b = 4 * e
        n1 = snap.elem_nodes_flat[b]
        n2 = snap.elem_nodes_flat[b + 1]
        n3 = snap.elem_nodes_flat[b + 2]
        n4 = snap.elem_nodes_flat[b + 3]
        tet = (n1, n2, n3, n4)
        pts = [node_xyz[t] for t in tet]
        cx = sum(p[0] for p in pts) / 4.0
        cy = sum(p[1] for p in pts) / 4.0
        cz = sum(p[2] for p in pts) / 4.0
        center = (cx, cy, cz)
        for tri in ((n1, n2, n3), (n1, n4, n2), (n2, n4, n3), (n1, n3, n4)):
            k = tuple(sorted(tri))
            faces.setdefault(k, []).append((tri, center))

    out: list[tuple[tuple[int, int, int], tuple[float, float, float], float]] = []
    for members in faces.values():
        if len(members) != 1:
            continue  # 내부면
        tri, tcenter = members[0]
        a = node_xyz[tri[0]]
        b = node_xyz[tri[1]]
        c = node_xyz[tri[2]]
        ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        nx = ab[1] * ac[2] - ab[2] * ac[1]
        ny = ab[2] * ac[0] - ab[0] * ac[2]
        nz = ab[0] * ac[1] - ab[1] * ac[0]
        ln = math.sqrt(nx * nx + ny * ny + nz * nz)
        if ln <= 1e-18:
            continue
        # tri 노말이 테트 중심 방향이면 반전해서 외향 노말로 맞춘다.
        fc = ((a[0] + b[0] + c[0]) / 3.0, (a[1] + b[1] + c[1]) / 3.0, (a[2] + b[2] + c[2]) / 3.0)
        to_tet = (tcenter[0] - fc[0], tcenter[1] - fc[1], tcenter[2] - fc[2])
        if nx * to_tet[0] + ny * to_tet[1] + nz * to_tet[2] > 0.0:
            nx, ny, nz = -nx, -ny, -nz
        unit = (nx / ln, ny / ln, nz / ln)
        area = 0.5 * ln
        out.append((tri, unit, area))
    return out


def _angle_to_plus_z_deg(unit_n: tuple[float, float, float]) -> float:
    """단위 법선과 전역 +Z 축 사이 각도 [0°, 180°]."""
    nz = max(-1.0, min(1.0, unit_n[2]))
    return math.degrees(math.acos(nz))


def _resolve_surface_pressure_load(
    load: SurfacePressureLoadV1, snap: MeshSnapshot
) -> list[tuple[int, int, float]]:
    if load.selection.kind != "exterior":
        raise ValueError(f"지원하지 않는 surface_pressure.selection: {load.selection.kind}")
    p = float(load.magnitude)
    max_tilt = load.selection.normal_max_tilt_deg
    # 압력 +값 = 외곽면 법선 반대(내향) 방향
    sign = -1.0
    acc: dict[tuple[int, int], float] = {}
    used_faces = 0
    for tri, n, area in _boundary_faces_with_outward_normals(snap):
        if max_tilt is not None:
            theta = _angle_to_plus_z_deg(n)
            if abs(theta - 90.0) > float(max_tilt):
                continue
        used_faces += 1
        fx = sign * p * n[0] * area / 3.0
        fy = sign * p * n[1] * area / 3.0
        fz = sign * p * n[2] * area / 3.0
        for nid in tri:
            if fx != 0.0:
                acc[(nid, 1)] = acc.get((nid, 1), 0.0) + fx
            if fy != 0.0:
                acc[(nid, 2)] = acc.get((nid, 2), 0.0) + fy
            if fz != 0.0:
                acc[(nid, 3)] = acc.get((nid, 3), 0.0) + fz
    if max_tilt is not None and used_faces == 0:
        raise ValueError(
            "surface_pressure exterior + normal_max_tilt_deg: 조건에 맞는 외곽면이 없습니다 "
            f"(tilt≤{max_tilt}°)."
        )
    return [(nid, dof, mag) for (nid, dof), mag in sorted(acc.items()) if abs(mag) > 1e-18]


def _tet_volume_m3(
    node_xyz: dict[int, tuple[float, float, float]],
    n1: int,
    n2: int,
    n3: int,
    n4: int,
) -> float:
    a = node_xyz[n1]
    b = node_xyz[n2]
    c = node_xyz[n3]
    d = node_xyz[n4]
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    ad = (d[0] - a[0], d[1] - a[1], d[2] - a[2])
    cx = ac[1] * ad[2] - ac[2] * ad[1]
    cy = ac[2] * ad[0] - ac[0] * ad[2]
    cz = ac[0] * ad[1] - ac[1] * ad[0]
    trip = ab[0] * cx + ab[1] * cy + ab[2] * cz
    return abs(trip) / 6.0


def _resolve_gravity_load(
    load: GravityLoadV1,
    snap: MeshSnapshot,
    *,
    density_kg_m3: float,
) -> list[tuple[int, int, float]]:
    ax, ay, az = (float(load.acceleration[0]), float(load.acceleration[1]), float(load.acceleration[2]))
    if ax == 0.0 and ay == 0.0 and az == 0.0:
        raise ValueError("gravity acceleration 벡터가 모두 0이면 안 됩니다.")
    if density_kg_m3 <= 0.0:
        raise ValueError("중력 하중 해석을 위해 밀도( material_density_kg_m3 또는 density_kg_m3 )가 양수여야 합니다.")

    node_xyz = {n.tag: (n.x, n.y, n.z) for n in snap.nodes}
    acc: dict[tuple[int, int], float] = {}
    n_elem = len(snap.elem_tags)
    for e in range(n_elem):
        b = 4 * e
        tet = (
            int(snap.elem_nodes_flat[b]),
            int(snap.elem_nodes_flat[b + 1]),
            int(snap.elem_nodes_flat[b + 2]),
            int(snap.elem_nodes_flat[b + 3]),
        )
        vol = _tet_volume_m3(node_xyz, tet[0], tet[1], tet[2], tet[3])
        if vol <= 1e-30:
            continue
        fx = density_kg_m3 * vol * ax / 4.0
        fy = density_kg_m3 * vol * ay / 4.0
        fz = density_kg_m3 * vol * az / 4.0
        for nid in tet:
            if fx != 0.0:
                acc[(nid, 1)] = acc.get((nid, 1), 0.0) + fx
            if fy != 0.0:
                acc[(nid, 2)] = acc.get((nid, 2), 0.0) + fy
            if fz != 0.0:
                acc[(nid, 3)] = acc.get((nid, 3), 0.0) + fz
    return [(nid, dof, mag) for (nid, dof), mag in sorted(acc.items()) if abs(mag) > 1e-18]


def resolve_static_linear_v1(
    spec: AnalysisInputV1,
    snap: MeshSnapshot,
    *,
    default_density_kg_m3: float = 7850.0,
) -> ResolvedStaticV1:
    fix_ids = _resolve_support_fix_tags(list(spec.supports), snap)
    dof_ranges = _dof_ranges(list(spec.supports[0].fixed_dofs))
    for s in spec.supports[1:]:
        if tuple(s.fixed_dofs) != tuple(spec.supports[0].fixed_dofs):
            raise ValueError("MVP: 모든 support 의 fixed_dofs 는 동일해야 합니다.")

    density_kg_m3 = (
        float(spec.material_density_kg_m3)
        if spec.material_density_kg_m3 is not None
        else float(default_density_kg_m3)
    )

    steps_out: list[ResolvedStepV1] = []
    for lc in spec.load_cases:
        chunk: list[tuple[int, int, float]] = []
        for ld in spec.loads:
            if ld.case_id == lc.id:
                if isinstance(ld, NodalForceLoadV1):
                    chunk.extend(_resolve_nodal_load(ld, snap))
                elif isinstance(ld, SurfacePressureLoadV1):
                    chunk.extend(_resolve_surface_pressure_load(ld, snap))
                elif isinstance(ld, GravityLoadV1):
                    chunk.extend(_resolve_gravity_load(ld, snap, density_kg_m3=density_kg_m3))
                else:
                    raise TypeError(type(ld))
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

    cloads_by_case = {s.case_id: s.cloads for s in steps_out}

    for comb in spec.combinations:
        acc: dict[tuple[int, int], float] = {}
        for case_id, fac in comb.factors.items():
            f = float(fac)
            for nid, dof, mag in cloads_by_case.get(case_id, ()):
                k = (int(nid), int(dof))
                acc[k] = acc.get(k, 0.0) + f * float(mag)
        merged = tuple(
            (nid, dof, m)
            for (nid, dof), m in sorted(acc.items())
            if abs(m) > 1e-18
        )
        if not merged:
            raise ValueError(
                f"조합 {comb.id!r}의 등가 CLOAD 가 모두 0입니다 (케이스 하중·계수를 확인하세요)."
            )
        steps_out.append(
            ResolvedStepV1(
                case_id=comb.id,
                case_name=comb.name,
                cloads=merged,
            )
        )

    return ResolvedStaticV1(
        fix_node_ids=tuple(fix_ids),
        boundary_dof_ranges=tuple(dof_ranges),
        steps=tuple(steps_out),
    )
