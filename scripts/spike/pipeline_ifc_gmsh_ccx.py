#!/usr/bin/env python3
"""
IFC → 중간 형상(STL) → Gmsh(3D 테트 메쉬) → CalculiX 입력(.inp) 초안

같은 Docker 이미지(pipeline-spike) 안에서 한 번에 돌릴 수 있는 **스파이크 뼈대**입니다.
- 중간 형상: IfcOpenShell geom 삼각망을 ASCII STL로 덤프 (MVP에서 STEP/BREP로 바꿀 여지를 주석으로 남김)
- Gmsh: STL merge 후 `classifySurfaces`(각도·reparam 조합) → `createGeometry` → 체적 메쉬를
  **여러 단계**로 시도하고, `auto` 모드에서는 실패 시 **OCC 바운딩 박스**로 폴백합니다.
- STEP/BREP 직접 임포트는 CAD 커널 추가가 필요해 본 스크립트에서는 시도하지 않습니다(리포트에 명시).
- CalculiX: Gmsh 3D 선형 사면체(TYPE=C3D4)만 *NODE / *ELEMENT 로 풀어 씀 (고차·다른 타입은 TODO)

경계/하중은 **자동 휴리스틱**(최소 Z 노드 고정, 최대 Z 노드에 수직 하중)이라 실제 구조와 다를 수 있습니다.
검증용·파이프라인 배선 확인 목적입니다.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import ifcopenshell
import ifcopenshell.geom
import gmsh

# Gmsh 요소 타입: 4 = 4-node tetrahedron (선형)
GMSH_TET4 = 4

STRUCTURAL_IFC_CLASSES: tuple[str, ...] = (
    "IfcBeam",
    "IfcColumn",
    "IfcMember",
    "IfcSlab",
    "IfcWall",
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


def _gmsh_write_msh_and_ccx_inp(
    msh_path: Path,
    inp_path: Path,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
) -> None:
    msh_path.parent.mkdir(parents=True, exist_ok=True)
    gmsh.write(str(msh_path))
    print("3) Gmsh mesh -> CalculiX .inp …", inp_path)
    write_ccx_inp_from_gmsh_mesh(
        inp_path,
        young_pa=young_pa,
        poisson=poisson,
        point_load_n=point_load_n,
    )


def _gmsh_occ_bbox_volume_mesh(verts: Sequence[float]) -> None:
    x0, y0, z0, dx, dy, dz = bbox_corner_and_size(verts)
    gmsh.model.occ.addBox(x0, y0, z0, dx, dy, dz)
    gmsh.model.occ.synchronize()
    gmsh.model.mesh.generate(3)


def gmsh_volume_mesh_write_msh_and_inp(
    stl_path: Path,
    verts: Sequence[float],
    msh_path: Path,
    inp_path: Path,
    *,
    mesh_size: float,
    young_pa: float,
    poisson: float,
    point_load_n: float,
    geometry_strategy: str = "auto",
) -> str:
    """
    STL -> (classifySurfaces 등) -> createGeometry -> 체적 메쉬 를 여러 전략으로 시도.
    - auto: classify 각도들 -> raw merge -> 실패 시 OCC bbox
    - stl_classify / stl_raw: 해당 전략만 (실패 시 예외, bbox 없음)
    - occ_bbox: STL 생략, IFC 정점 bbox만

    반환: 실제로 성공한 Gmsh 체적 전략 이름.
    """
    allow_bbox_fallback = geometry_strategy in ("auto", "occ_bbox")
    attempts = _stl_volume_attempts(geometry_strategy)

    if geometry_strategy == "occ_bbox":
        gmsh.initialize()
        try:
            _gmsh_set_mesh_size(mesh_size)
            _gmsh_occ_bbox_volume_mesh(verts)
            _gmsh_write_msh_and_ccx_inp(
                msh_path, inp_path, young_pa=young_pa, poisson=poisson, point_load_n=point_load_n
            )
            return "occ_bbox_only"
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
                msh_path, inp_path, young_pa=young_pa, poisson=poisson, point_load_n=point_load_n
            )
            gmsh.finalize()
            return name
        except Exception as e:
            print(f"WARN Gmsh strategy [{name}]: {e}", file=sys.stderr)
            gmsh.finalize()

    if allow_bbox_fallback:
        gmsh.initialize()
        try:
            _gmsh_set_mesh_size(mesh_size)
            _gmsh_occ_bbox_volume_mesh(verts)
            _gmsh_write_msh_and_ccx_inp(
                msh_path, inp_path, young_pa=young_pa, poisson=poisson, point_load_n=point_load_n
            )
            return "occ_bbox_fallback"
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


def _ccx_data_lines_ints(ids: Sequence[int], *, max_per_line: int = 16) -> list[str]:
    """CalculiX splitline: 한 줄에 max_per_line 개를 넘기지 않도록 쉼표 구분 행으로 나눔."""
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


def _gmsh_volume_tet4_connectivity() -> tuple[list[int], list[int]]:
    """현재 Gmsh 모델에서 3D 선형 사면체만 (태그, 노드4개씩 플랫)."""
    elem_types, elem_tags, node_tags = gmsh.model.mesh.getElements(dim=3)
    out_tags: list[int] = []
    out_nodes: list[int] = []
    for etype, tags, nodes in zip(elem_types, elem_tags, node_tags):
        if etype != GMSH_TET4:
            continue
        n_elem = len(tags)
        for e in range(n_elem):
            out_tags.append(tags[e])
            base = 4 * e
            out_nodes.extend(
                [nodes[base], nodes[base + 1], nodes[base + 2], nodes[base + 3]]
            )
    return out_tags, out_nodes


def write_ccx_inp_from_gmsh_mesh(
    inp_path: Path,
    *,
    young_pa: float,
    poisson: float,
    point_load_n: float,
) -> None:
    """
    열린 Gmsh 세션에서 메쉬를 읽어 CalculiX .inp 작성 (C3D4만).
    gmsh.initialize() 직후, mesh.generate(3)까지 끝난 상태에서 호출하고,
    호출부에서 finalize() 전에 실행해야 합니다.
    """
    node_tags, coord, _ = gmsh.model.mesh.getNodes()
    if len(node_tags) == 0:
        raise RuntimeError("Gmsh: 노드가 없습니다.")

    tags_list = [int(t) for t in node_tags]
    coords = [float(c) for c in coord]
    n_nodes = len(tags_list)
    xs = coords[0::3]
    ys = coords[1::3]
    zs = coords[2::3]

    elem_tags, elem_nodes = _gmsh_volume_tet4_connectivity()
    if not elem_tags:
        raise RuntimeError(
            "Gmsh: 3D 선형 사면체(TYPE 4)가 없습니다. 메쉬 차수·알고리즘을 확인하세요."
        )

    z_min = min(zs)
    z_max = max(zs)
    dz = z_max - z_min
    tol = max(dz * 1.0e-6, 1.0e-9)

    fix_nodes = [tags_list[i] for i in range(n_nodes) if zs[i] <= z_min + tol]
    if not fix_nodes:
        fix_nodes = [tags_list[zs.index(z_min)]]

    # 하중 노드: z 최대에 가장 가까운 노드 하나
    load_node = tags_list[max(range(n_nodes), key=lambda i: zs[i])]

    lines: list[str] = [
        "*HEADING",
        "OpenBIM-Deflect spike: auto IFC-STL-Gmsh-C3D4 (match --young/--load-z to model units)",
        "*NODE",
    ]
    for i in range(n_nodes):
        nid = tags_list[i]
        lines.append(f"{nid:7d}, {xs[i]:.6e}, {ys[i]:.6e}, {zs[i]:.6e}")

    lines.append("*ELEMENT, TYPE=C3D4, ELSET=EALL")
    n_elem = len(elem_tags)
    for e in range(n_elem):
        tid = elem_tags[e]
        b = 4 * e
        n1, n2, n3, n4 = (
            elem_nodes[b],
            elem_nodes[b + 1],
            elem_nodes[b + 2],
            elem_nodes[b + 3],
        )
        lines.append(f"{tid:7d}, {n1:7d}, {n2:7d}, {n3:7d}, {n4:7d}")

    fix_set = "FIXZMIN"
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
    lines.append(f"{load_node}, 3, {-point_load_n:.6e}")
    lines.append(f"*NODE FILE, NSET={all_set}")
    lines.append("U")
    lines.append("*EL FILE, ELSET=EALL")
    lines.append("S, NOE")
    lines.append(f"*NODE PRINT, NSET={all_set}")
    lines.append("U")
    lines.append("*END STEP")

    inp_path.parent.mkdir(parents=True, exist_ok=True)
    inp_path.write_text("\n".join(lines) + "\n", encoding="ascii")


def write_pipeline_report(
    out_dir: Path,
    *,
    geometry_strategy_requested: str,
    gmsh_volume_strategy: str,
) -> None:
    report = {
        "version": 1,
        "geometry_strategy_requested": geometry_strategy_requested,
        "gmsh_volume_strategy": gmsh_volume_strategy,
        "geometry_source": "ifcopenshell_tessellation_stl",
        "step_brep_import": False,
        "notes": (
            "IFC BREP/STEP 직접 경로는 pythonocc 등 별도 커널이 있으면 추가 가능. "
            "현재는 삼각망 STL + Gmsh classify/raw/bbox 입니다."
        ),
    }
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
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stl_path = out_dir / "intermediate_from_ifc.stl"
    msh_path = out_dir / "volume_from_gmsh.msh"
    inp_path = out_dir / "model_from_pipeline.inp"

    f = ifcopenshell.open(str(ifc_path))
    product = pick_first_structural_product(f)
    print("IFC product:", product.is_a(), "GlobalId:", product.GlobalId)

    verts, faces = ifc_product_triangulation(product)
    print("1) IFC → STL …", stl_path)
    ifc_product_to_stl(product, stl_path, verts, faces)

    print("2) STL -> Gmsh 3D mesh (strategy=%s) …" % geometry_strategy, msh_path)
    gmsh_used = gmsh_volume_mesh_write_msh_and_inp(
        stl_path,
        verts,
        msh_path,
        inp_path,
        mesh_size=mesh_size,
        young_pa=young_pa,
        poisson=poisson,
        point_load_n=point_load_n,
        geometry_strategy=geometry_strategy,
    )
    write_pipeline_report(
        out_dir,
        geometry_strategy_requested=geometry_strategy,
        gmsh_volume_strategy=gmsh_used,
    )

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

    print("pipeline skeleton: OK →", out_dir)


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
        default=120.0,
        help="Gmsh 특성 길이 상한 (IFC/모델 길이 단위와 동일; sample/simple_beam.ifc 는 mm)",
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
    )


if __name__ == "__main__":
    main()
