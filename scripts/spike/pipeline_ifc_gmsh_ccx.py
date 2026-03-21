#!/usr/bin/env python3
"""
IFC → 중간 형상(STL) → Gmsh(3D 테트 메쉬) → CalculiX 입력(.inp) 초안

같은 Docker 이미지(pipeline-spike) 안에서 한 번에 돌릴 수 있는 **스파이크 뼈대**입니다.
- 중간 형상: IfcOpenShell geom 삼각망을 ASCII STL로 덤프 (MVP에서 STEP/BREP로 바꿀 여지를 주석으로 남김)
- Gmsh: `auto` 는 **정점 AABB 체적**을 먼저 시도하고, 실패 시 STL merge·`classifySurfaces`(각도·reparam) →
  `createGeometry` → 체적 메쉬를 **여러 단계**로 시도하며, 끝까지 실패하면 **OCC 바운딩 박스**로 폴백합니다.
- STEP/BREP 직접 임포트는 CAD 커널 추가가 필요해 본 스크립트에서는 시도하지 않습니다(리포트에 명시).
- CalculiX: Gmsh 3D 선형 사면체(TYPE=C3D4)만 *NODE / *ELEMENT 로 풀어 씀 (고차·다른 타입은 TODO)

경계/하중은 **자동 휴리스틱**(최소 Z 노드 고정, 최대 Z 노드에 수직 하중)이라 실제 구조와 다를 수 있습니다.
검증용·파이프라인 배선 확인 목적입니다.

**길이 단위:** IfcOpenShell `USE_WORLD_COORDS` 삼각망은 일반적으로 **미터(SI)** 입니다(IFC가 mm여도 내부에서 m로 나오는 경우가 많음).
`--mesh-size` 는 Gmsh 특성 길이 상한으로 **모델 좌표와 같은 단위**여야 합니다(예: m 스케일이면 `0.2`~`0.5`, 과거 기본값 `120`은 “120m 셀”로 거칠거나 혼동을 줌).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ElementUtil
import gmsh

_REPO_ROOT = Path(__file__).resolve().parents[2]
_backend = _REPO_ROOT / "backend"
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.analysis.ccx_gmsh_write import (
    write_analysis_input_sidecar,
    write_ccx_inp_from_gmsh_session,
)
from app.analysis.ifc_elset_partition import (
    axis_aligned_bbox_from_verts,
    elset_name_for_global_id,
)

# Gmsh 요소 타입: 4 = 4-node tetrahedron (선형)
GMSH_TET4 = 4

# auto: 과거에는 병합 삼각형이 ~256개를 넘으면 bbox 를 건너뛰고 classify 만 시도해
# (ten_story 50부재 ≈600삼각형) 매우 느려질 수 있었음. 현재는 삼각형 수와 무관하게 bbox 를 먼저 시도.

STRUCTURAL_IFC_CLASSES: tuple[str, ...] = (
    "IfcBeam",
    "IfcColumn",
    "IfcMember",
    "IfcSlab",
    "IfcWall",
)

PSET_OPENBIM_DEFLECT = "OpenBIM_Deflect"
PROP_LOAD_Z_N = "AppliedLoad_Z_N"
PROP_BOUNDARY_MODE = "BoundaryMode"
VALID_BC_MODES: tuple[str, ...] = (
    "FIX_MIN_Z_LOAD_MAX_Z",
    "FIX_MIN_Y_LOAD_MAX_Y",
    "FIX_MIN_Z_LOAD_TOP_X",
    "FIX_MIN_Z_LOAD_TOP_Y",
)


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def pick_first_structural_product(f: ifcopenshell.file) -> ifcopenshell.entity_instance:
    for cls in STRUCTURAL_IFC_CLASSES:
        found = f.by_type(cls)
        if found:
            return found[0]
    raise LookupError(
        f"IFC에 다음 타입 중 하나가 필요합니다: {', '.join(STRUCTURAL_IFC_CLASSES)}"
    )


def collect_structural_products(f: ifcopenshell.file) -> list[ifcopenshell.entity_instance]:
    """타입 순서대로 모든 구조 부재(중복 GlobalId 제외)."""
    out: list[ifcopenshell.entity_instance] = []
    seen: set[str] = set()
    for cls in STRUCTURAL_IFC_CLASSES:
        for p in f.by_type(cls):
            gid = getattr(p, "GlobalId", None) or str(p.id())
            if gid in seen:
                continue
            seen.add(gid)
            out.append(p)
    return out


def read_openbim_deflect_hints(f: ifcopenshell.file) -> tuple[float | None, str | None]:
    """IfcProject / IfcSite / IfcBuilding 의 Pset `OpenBIM_Deflect` 에서 하중·경계 힌트."""
    load_n: float | None = None
    bc_mode: str | None = None
    roots: list[ifcopenshell.entity_instance] = []
    roots.extend(f.by_type("IfcProject") or [])
    roots.extend(f.by_type("IfcSite") or [])
    roots.extend(f.by_type("IfcBuilding") or [])
    for ent in roots:
        try:
            psets = ElementUtil.get_psets(ent)
        except Exception:
            continue
        block = psets.get(PSET_OPENBIM_DEFLECT)
        if not block:
            continue
        raw_l = block.get(PROP_LOAD_Z_N)
        if raw_l is not None:
            try:
                load_n = float(raw_l)
            except (TypeError, ValueError):
                pass
        raw_b = block.get(PROP_BOUNDARY_MODE)
        if raw_b is not None:
            s = str(raw_b).strip()
            if s in VALID_BC_MODES:
                bc_mode = s
        break
    return load_n, bc_mode


def collect_ifc_product_partition(
    products: Sequence[ifcopenshell.entity_instance],
) -> list[tuple[str, str, tuple[float, float, float, float, float, float]]]:
    """IFC 부재별 (CalculiX ELSET 이름, GlobalId, AABB6) — 병합 메쉬에서 요소 ELSET 분할용."""
    out: list[tuple[str, str, tuple[float, float, float, float, float, float]]] = []
    for p in products:
        v, _ = ifc_product_triangulation(p)
        bb = axis_aligned_bbox_from_verts(v)
        gid = getattr(p, "GlobalId", None) or str(p.id())
        ename = elset_name_for_global_id(str(gid))
        out.append((ename, str(gid), bb))
    return out


def merge_structural_meshes(
    products: Sequence[ifcopenshell.entity_instance],
) -> tuple[tuple[float, ...], tuple[int, ...]]:
    """여러 부재 삼각망을 단일 정점·면 목록으로 병합."""
    if not products:
        raise LookupError("병합할 구조 부재가 없습니다.")
    all_v: list[float] = []
    all_f: list[int] = []
    off = 0
    for p in products:
        v, fc = ifc_product_triangulation(p)
        nv = len(v) // 3
        all_v.extend(v)
        for i in range(0, len(fc), 3):
            all_f.extend((fc[i] + off, fc[i + 1] + off, fc[i + 2] + off))
        off += nv
    return tuple(all_v), tuple(all_f)


def ifc_product_triangulation(
    product: ifcopenshell.entity_instance,
) -> tuple[tuple[float, ...], tuple[int, ...]]:
    """IfcOpenShell geom으로 정점·삼각형 인덱스를 한 번만 계산."""
    settings = ifcopenshell.geom.settings()
    settings.set(settings.USE_WORLD_COORDS, True)
    settings.set(settings.WELD_VERTICES, True)
    settings.set(settings.DISABLE_OPENING_SUBTRACTIONS, True)

    shape = ifcopenshell.geom.create_shape(settings, product)
    geo = shape.geometry
    verts: tuple[float, ...] = tuple(geo.verts)
    faces: tuple[int, ...] = tuple(geo.faces)
    if len(verts) < 9 or len(faces) < 9:
        raise ValueError("추출된 삼각망이 비정상적으로 작습니다. IFC 형상·설정을 확인하세요.")
    return verts, faces


def ifc_product_to_stl(
    product: ifcopenshell.entity_instance,
    stl_path: Path,
    verts: Sequence[float],
    faces: Sequence[int],
) -> None:
    """IfcOpenShell geom 삼각형을 ASCII STL로 기록 (중간 형상)."""
    write_ascii_stl(stl_path, verts, faces, solid_name=product.is_a())


def bbox_corner_and_size(verts: Sequence[float]) -> tuple[float, float, float, float, float, float]:
    """축정렬 AABB: (xmin, ymin, zmin, dx, dy, dz)."""
    xs = verts[0::3]
    ys = verts[1::3]
    zs = verts[2::3]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    dx = max(xmax - xmin, 1e-9)
    dy = max(ymax - ymin, 1e-9)
    dz = max(zmax - zmin, 1e-9)
    return xmin, ymin, zmin, dx, dy, dz


def _gmsh_set_mesh_size(mesh_size: float) -> None:
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size * 0.2)


def _gmsh_try_stl_options() -> None:
    """STL 병합 후 메쉬 길이 힌트(버전에 없는 옵션은 무시)."""
    for opt, val in (
        ("Mesh.CharacteristicLengthFromCurvature", 0),
        ("Mesh.CharacteristicLengthFromPoints", 0),
    ):
        try:
            gmsh.option.setNumber(opt, val)
        except Exception:
            pass


def _gmsh_surface_loop_and_volume_mesh_3d() -> None:
    surfaces = gmsh.model.getEntities(2)
    if not surfaces:
        raise RuntimeError("Gmsh: createGeometry 후 2D surface 없음")
    surface_tags = [s[1] for s in surfaces]
    loop = gmsh.model.geo.addSurfaceLoop(surface_tags)
    gmsh.model.geo.addVolume([loop])
    gmsh.model.geo.synchronize()
    gmsh.model.mesh.generate(3)


def _gmsh_classify_surface_angle(deg: float, *, reparam: bool) -> None:
    a = math.radians(deg)
    gmsh.model.mesh.classifySurfaces(
        a,
        boundary=True,
        forReparametrization=reparam,
        curveAngle=a,
        exportDiscrete=True,
    )


def _stl_volume_attempts(geometry_strategy: str) -> list[tuple[str, object]]:
    """(이름, merge 후 호출할 전처리 callable) 리스트. stl_raw는 전처리 없음."""

    def pre_classify(deg: float, reparam: bool):
        def _() -> None:
            _gmsh_classify_surface_angle(deg, reparam=reparam)

        return _

    classify_steps: list[tuple[str, object]] = [
        ("stl_classify_40deg", pre_classify(40.0, False)),
        ("stl_classify_40deg_reparam", pre_classify(40.0, True)),
        ("stl_classify_90deg", pre_classify(90.0, False)),
        ("stl_classify_180deg", pre_classify(180.0, False)),
        ("stl_classify_180deg_reparam", pre_classify(180.0, True)),
    ]
    raw: tuple[str, object] = ("stl_raw", lambda: None)

    if geometry_strategy == "auto":
        return [*classify_steps, raw]
    if geometry_strategy == "stl_classify":
        return classify_steps
    if geometry_strategy == "stl_raw":
        return [raw]
    if geometry_strategy == "occ_bbox":
        return []
    raise ValueError(f"unknown geometry_strategy: {geometry_strategy}")


def _capture_gmsh_volume_stats(stats_out: dict[str, Any]) -> None:
    tags, _, _ = gmsh.model.mesh.getNodes()
    stats_out["n_mesh_nodes"] = int(len(tags))
    elem_types, elem_tags, _ = gmsh.model.mesh.getElements(dim=3)
    n_tet = 0
    for et, tgs in zip(elem_types, elem_tags):
        if et == GMSH_TET4:
            n_tet += len(tgs)
    stats_out["n_mesh_tets"] = n_tet


def _gmsh_write_msh_and_ccx_inp(
    msh_path: Path,
    inp_path: Path,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    bc_mode: str,
    stats_out: dict[str, Any] | None = None,
    analysis_spec: dict[str, Any] | None = None,
    ifc_product_partition: list[tuple[str, str, tuple[float, float, float, float, float, float]]]
    | None = None,
    density_kg_m3: float = 7850.0,
) -> None:
    msh_path.parent.mkdir(parents=True, exist_ok=True)
    if stats_out is not None:
        _capture_gmsh_volume_stats(stats_out)
    gmsh.write(str(msh_path))
    print("3) Gmsh mesh -> CalculiX .inp …", inp_path)
    write_ccx_inp_from_gmsh_session(
        inp_path,
        young_pa=young_pa,
        poisson=poisson,
        point_load_n=point_load_n,
        bc_mode=bc_mode,
        analysis_spec=analysis_spec,
        stats_out=stats_out,
        ifc_product_partition=ifc_product_partition,
        density_kg_m3=density_kg_m3,
    )


def _gmsh_occ_bbox_volume_mesh(verts: Sequence[float]) -> None:
    x0, y0, z0, dx, dy, dz = bbox_corner_and_size(verts)
    gmsh.model.occ.addBox(x0, y0, z0, dx, dy, dz)
    gmsh.model.occ.synchronize()
    gmsh.model.mesh.generate(3)


def gmsh_volume_mesh_write_msh_and_inp(
    stl_path: Path,
    verts: Sequence[float],
    faces: Sequence[int],
    msh_path: Path,
    inp_path: Path,
    *,
    mesh_size: float,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    geometry_strategy: str = "auto",
    bc_mode: str = "FIX_MIN_Z_LOAD_MAX_Z",
    analysis_spec: dict[str, Any] | None = None,
    ifc_product_partition: list[tuple[str, str, tuple[float, float, float, float, float, float]]]
    | None = None,
    density_kg_m3: float = 7850.0,
) -> tuple[str, dict[str, Any]]:
    """
    STL -> (classifySurfaces 등) -> createGeometry -> 체적 메쉬 를 여러 전략으로 시도.
    - auto: **정점 AABB 체적 메쉬를 항상 먼저** 시도(빠름). 실패 시 classify 각도들 → raw → OCC bbox 폴백
    - stl_classify / stl_raw: 해당 전략만 (실패 시 예외, bbox 없음)
    - occ_bbox: STL 생략, IFC 정점 bbox만

    반환: (실제로 성공한 Gmsh 체적 전략 이름, 메쉬 통계 dict).
    """
    mesh_stats: dict[str, Any] = {}
    allow_bbox_fallback = geometry_strategy in ("auto", "occ_bbox")
    attempts = _stl_volume_attempts(geometry_strategy)

    if geometry_strategy == "occ_bbox":
        gmsh.initialize()
        try:
            _gmsh_set_mesh_size(mesh_size)
            _gmsh_occ_bbox_volume_mesh(verts)
            _gmsh_write_msh_and_ccx_inp(
                msh_path,
                inp_path,
                young_pa=young_pa,
                poisson=poisson,
                point_load_n=point_load_n,
                bc_mode=bc_mode,
                analysis_spec=analysis_spec,
                stats_out=mesh_stats,
                ifc_product_partition=ifc_product_partition,
                density_kg_m3=density_kg_m3,
            )
            return "occ_bbox_only", mesh_stats
        finally:
            gmsh.finalize()

    # auto: 삼각형 개수와 무관하게 AABB 먼저(병합 STL은 삼각형이 조금만 많아도 classify 가 매우 느림)
    if geometry_strategy == "auto":
        n_tris = len(faces) // 3
        gmsh.initialize()
        try:
            _gmsh_set_mesh_size(mesh_size)
            _gmsh_occ_bbox_volume_mesh(verts)
            _gmsh_write_msh_and_ccx_inp(
                msh_path,
                inp_path,
                young_pa=young_pa,
                poisson=poisson,
                point_load_n=point_load_n,
                bc_mode=bc_mode,
                analysis_spec=analysis_spec,
                stats_out=mesh_stats,
                ifc_product_partition=ifc_product_partition,
                density_kg_m3=density_kg_m3,
            )
            return "occ_bbox_fast", mesh_stats
        except Exception as e:
            print(
                f"WARN Gmsh auto bbox-first (n_tris={n_tris}): {e}",
                file=sys.stderr,
            )
        finally:
            gmsh.finalize()

    for name, pre in attempts:
        gmsh.initialize()
        try:
            _gmsh_set_mesh_size(mesh_size)
            gmsh.merge(str(stl_path))
            _gmsh_try_stl_options()
            pre()
            gmsh.model.mesh.createGeometry()
            _gmsh_surface_loop_and_volume_mesh_3d()
            _gmsh_write_msh_and_ccx_inp(
                msh_path,
                inp_path,
                young_pa=young_pa,
                poisson=poisson,
                point_load_n=point_load_n,
                bc_mode=bc_mode,
                analysis_spec=analysis_spec,
                stats_out=mesh_stats,
                ifc_product_partition=ifc_product_partition,
                density_kg_m3=density_kg_m3,
            )
            gmsh.finalize()
            return name, mesh_stats
        except Exception as e:
            print(f"WARN Gmsh strategy [{name}]: {e}", file=sys.stderr)
            gmsh.finalize()

    if allow_bbox_fallback:
        gmsh.initialize()
        try:
            _gmsh_set_mesh_size(mesh_size)
            _gmsh_occ_bbox_volume_mesh(verts)
            _gmsh_write_msh_and_ccx_inp(
                msh_path,
                inp_path,
                young_pa=young_pa,
                poisson=poisson,
                point_load_n=point_load_n,
                bc_mode=bc_mode,
                analysis_spec=analysis_spec,
                stats_out=mesh_stats,
                ifc_product_partition=ifc_product_partition,
                density_kg_m3=density_kg_m3,
            )
            return "occ_bbox_fallback", mesh_stats
        finally:
            gmsh.finalize()

    raise RuntimeError(
        "Gmsh: STL 기반 체적 메쉬에 실패했고, geometry_strategy 에 bbox 폴백이 없습니다."
    )


def write_ascii_stl(path: Path, verts: Sequence[float], faces: Sequence[int], *, solid_name: str) -> None:
    """verts: [x0,y0,z0, ...], faces: [i,j,k, ...] 삼각형별 3정점 인덱스 (IfcOpenShell 관례: 0-base)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in solid_name)[:40] or "solid"
    with path.open("w", encoding="ascii") as fp:
        fp.write(f"solid {safe}\n")
        n_tri = len(faces) // 3
        for t in range(n_tri):
            i, j, k = faces[3 * t], faces[3 * t + 1], faces[3 * t + 2]
            ax, ay, az = verts[3 * i], verts[3 * i + 1], verts[3 * i + 2]
            bx, by, bz = verts[3 * j], verts[3 * j + 1], verts[3 * j + 2]
            cx, cy, cz = verts[3 * k], verts[3 * k + 1], verts[3 * k + 2]
            ab = (bx - ax, by - ay, bz - az)
            ac = (cx - ax, cy - ay, cz - az)
            nx = ab[1] * ac[2] - ab[2] * ac[1]
            ny = ab[2] * ac[0] - ab[0] * ac[2]
            nz = ab[0] * ac[1] - ab[1] * ac[0]
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            nx, ny, nz = nx / ln, ny / ln, nz / ln
            fp.write(f"facet normal {nx:.6e} {ny:.6e} {nz:.6e}\n")
            fp.write("  outer loop\n")
            fp.write(f"    vertex {ax:.6e} {ay:.6e} {az:.6e}\n")
            fp.write(f"    vertex {bx:.6e} {by:.6e} {bz:.6e}\n")
            fp.write(f"    vertex {cx:.6e} {cy:.6e} {cz:.6e}\n")
            fp.write("  endloop\n")
            fp.write("endfacet\n")
        fp.write(f"endsolid {safe}\n")


def write_pipeline_report(
    out_dir: Path,
    *,
    geometry_strategy_requested: str,
    gmsh_volume_strategy: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    report: dict[str, Any] = {
        "version": 1,
        "geometry_strategy_requested": geometry_strategy_requested,
        "gmsh_volume_strategy": gmsh_volume_strategy,
        "geometry_source": "ifcopenshell_tessellation_stl",
        "step_brep_import": False,
        "notes": (
            "IFC BREP/STEP 직접 경로는 pythonocc 등 별도 커널이 있으면 추가 가능. "
            "현재는 삼각망 STL + Gmsh classify/raw/bbox 입니다. "
            "IfcOpenShell 월드 좌표는 보통 m; mesh_size 는 동일 단위(예 0.25)."
        ),
    }
    if metrics:
        report.update(metrics)
    (out_dir / "pipeline_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def run_pipeline(
    ifc_path: Path,
    out_dir: Path,
    *,
    mesh_size: float,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    run_ccx: bool,
    geometry_strategy: str = "auto",
    first_product_only: bool = False,
    boundary_mode_cli: str | None = None,
    analysis_spec_path: Path | None = None,
    partition_ifc_elsets: bool = False,
    density_kg_m3: float = 7850.0,
) -> None:
    t_wall0 = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)
    stl_path = out_dir / "intermediate_from_ifc.stl"
    msh_path = out_dir / "volume_from_gmsh.msh"
    inp_path = out_dir / "model_from_pipeline.inp"

    analysis_spec: dict[str, Any] | None = None
    if analysis_spec_path is not None:
        ap = Path(analysis_spec_path)
        if ap.is_file():
            analysis_spec = json.loads(ap.read_text(encoding="utf-8"))
            write_analysis_input_sidecar(out_dir, analysis_spec)

    f = ifcopenshell.open(str(ifc_path))
    load_ifc, bc_ifc = read_openbim_deflect_hints(f)
    effective_load = load_ifc if load_ifc is not None else point_load_n
    if boundary_mode_cli and boundary_mode_cli in VALID_BC_MODES:
        effective_bc = boundary_mode_cli
    elif bc_ifc:
        effective_bc = bc_ifc
    else:
        effective_bc = "FIX_MIN_Z_LOAD_MAX_Z"

    if first_product_only:
        products = [pick_first_structural_product(f)]
    else:
        products = collect_structural_products(f)
    if not products:
        raise SystemExit(
            f"IFC에 구조 부재가 없습니다: {', '.join(STRUCTURAL_IFC_CLASSES)}"
        )

    verts, faces = merge_structural_meshes(products)
    n_tris = len(faces) // 3
    n_verts = len(verts) // 3
    labels = ",".join(f"{p.is_a()}:{getattr(p, 'GlobalId', '?')[:8]}" for p in products[:5])
    if len(products) > 5:
        labels += f",…(+{len(products) - 5})"
    print(
        f"1) IFC → STL … {len(products)} product(s) [{labels}] ({n_verts} verts, {n_tris} tris)",
        stl_path,
    )
    write_ascii_stl(stl_path, verts, faces, solid_name="MergedStructural")

    ifc_partition: list[tuple[str, str, tuple[float, float, float, float, float, float]]] | None = None
    if partition_ifc_elsets:
        ifc_partition = collect_ifc_product_partition(products)
        print(
            f"   IFC ELSET partition: {len(ifc_partition)} product(s) → AABB centroid → ELSET (see ifc_elset_map.json)",
            file=sys.stderr,
        )

    print("2) STL -> Gmsh 3D mesh (strategy=%s) …" % geometry_strategy, msh_path)
    gmsh_used, mesh_stats = gmsh_volume_mesh_write_msh_and_inp(
        stl_path,
        verts,
        faces,
        msh_path,
        inp_path,
        mesh_size=mesh_size,
        young_pa=young_pa,
        poisson=poisson,
        point_load_n=effective_load,
        geometry_strategy=geometry_strategy,
        bc_mode=effective_bc,
        analysis_spec=analysis_spec,
        ifc_product_partition=ifc_partition,
        density_kg_m3=density_kg_m3,
    )
    metrics: dict[str, Any] = {
        **mesh_stats,
        "n_ifc_triangles": n_tris,
        "n_ifc_vertices": n_verts,
        "n_structural_products": len(products),
        "ifc_applied_load_z_n": effective_load,
        "bc_mode": effective_bc,
        "ifc_load_from_pset": load_ifc is not None,
        "ifc_bc_from_pset": bc_ifc is not None,
        "analysis_input_v1": analysis_spec is not None,
        "partition_ifc_elsets": bool(partition_ifc_elsets),
    }

    if run_ccx:
        job = inp_path.stem
        with tempfile.TemporaryDirectory(prefix="openbim_ccx_pipeline_") as td:
            tdir = Path(td)
            shutil.copy(inp_path, tdir / f"{job}.inp")
            print("4) ccx", job, "… (cwd tmp)")
            r = subprocess.run(
                ["ccx", job],
                cwd=str(tdir),
                text=True,
                capture_output=True,
            )
            if r.returncode != 0:
                err = (r.stderr or r.stdout or "").strip()
                print(err[-6000:] if err else "(no ccx stderr)", file=sys.stderr)
                raise SystemExit(f"ccx failed: {r.returncode}")
            frd = tdir / f"{job}.frd"
            if frd.is_file():
                out_frd = out_dir / frd.name
                shutil.copy(frd, out_frd)
                print("   wrote", out_frd, out_frd.stat().st_size, "bytes")
            else:
                print("WARN: ccx finished but .frd not found", file=sys.stderr)

    metrics["elapsed_seconds"] = round(time.perf_counter() - t_wall0, 3)
    write_pipeline_report(
        out_dir,
        geometry_strategy_requested=geometry_strategy,
        gmsh_volume_strategy=gmsh_used,
        metrics=metrics,
    )
    print("pipeline skeleton: OK →", out_dir, f"({metrics['elapsed_seconds']} s)")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--ifc",
        type=Path,
        default=_root_dir() / "sample" / "simple_beam.ifc",
        help="입력 IFC 경로",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=_root_dir() / "scripts" / "spike" / "_output",
        help="STL / msh / inp 출력 디렉터리",
    )
    p.add_argument(
        "--mesh-size",
        type=float,
        default=0.25,
        help="Gmsh 특성 길이 상한 (IfcOpenShell 월드 좌표와 동일 단위; 보통 m → 예: 0.2~0.5)",
    )
    # sample IFC 좌표가 mm일 때 흔한 조합: MPa, N, mm
    p.add_argument(
        "--young",
        type=float,
        default=210_000.0,
        help="영률 (mm+N+MPa 체계면 [MPa], m+N+Pa 체계면 [Pa])",
    )
    p.add_argument("--poisson", type=float, default=0.3, help="포아송비")
    p.add_argument(
        "--density-kg-m3",
        type=float,
        default=7850.0,
        help="중력(AnalysisInputV1 gravity) 등가 C3D4 질량 환산용 밀도 [kg/m³] (스펙 material_density_kg_m3 가 없을 때)",
    )
    p.add_argument(
        "--load-z",
        type=float,
        default=10_000.0,
        help="전역 -Z 방향 절점 하중 크기 [N] (스파이크용 단일 노드)",
    )
    p.add_argument(
        "--run-ccx",
        action="store_true",
        help="생성 직후 ccx로 1회 실행하고 .frd를 out-dir에 복사",
    )
    p.add_argument(
        "--geometry-strategy",
        choices=("auto", "stl_classify", "stl_raw", "occ_bbox"),
        default="auto",
        help="체적 메쉬: auto=classify+raw 후 bbox 폴백; stl_classify|stl_raw=bbox 없음; occ_bbox=STL 생략",
    )
    p.add_argument(
        "--first-product-only",
        action="store_true",
        help="구조 부재 중 첫 요소만 (이전 단일 부재 동작)",
    )
    p.add_argument(
        "--boundary-mode",
        choices=VALID_BC_MODES,
        default=None,
        help="IFC OpenBIM_Deflect 보다 우선하는 경계·하중 축 모드",
    )
    p.add_argument(
        "--analysis-spec",
        type=Path,
        default=None,
        help="AnalysisInputV1 JSON 경로 — 있으면 bc_mode·load-z 대신 구조화 하중·지지 (docs/LOAD-MODEL-AND-INP.md)",
    )
    p.add_argument(
        "--partition-ifc-elsets",
        action="store_true",
        help="IFC 부재별 GlobalId → CalculiX ELSET (병합 체적 메쉬에서 사면체 중심 vs 부재 AABB). ifc_elset_map.json 생성",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    if not args.ifc.is_file():
        raise SystemExit(f"IFC 없음: {args.ifc}")
    run_pipeline(
        args.ifc,
        args.out_dir,
        mesh_size=args.mesh_size,
        young_pa=args.young,
        poisson=args.poisson,
        point_load_n=args.load_z,
        run_ccx=args.run_ccx,
        geometry_strategy=args.geometry_strategy,
        first_product_only=args.first_product_only,
        boundary_mode_cli=args.boundary_mode,
        analysis_spec_path=args.analysis_spec,
        partition_ifc_elsets=args.partition_ifc_elsets,
        density_kg_m3=args.density_kg_m3,
    )


if __name__ == "__main__":
    main()
