#!/usr/bin/env python3
"""MVP 검증용 IFC를 코드로 생성합니다.

- 단일 IfcBeam / IfcColumn (기존)
- 10층 × (기둥 4 + 슬래브 1) 모듈, 전고 약 1 m (`ten_story_4columns_slab.ifc`)

실행 (저장소 루트에서 venv 사용 예):

    .venv/bin/pip install -r sample/requirements.txt
    .venv/bin/python sample/generate_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import ifcopenshell
import numpy as np
from ifcopenshell.api.aggregate import assign_object
from ifcopenshell.api.context import add_context
from ifcopenshell.api.geometry import (
    add_profile_representation,
    add_slab_representation,
    assign_representation,
    edit_object_placement,
)
from ifcopenshell.api.profile import add_parameterized_profile
from ifcopenshell.api.project import create_file
from ifcopenshell.api.pset import add_pset, edit_pset
from ifcopenshell.api.root import create_entity
from ifcopenshell.api.spatial import assign_container
from ifcopenshell.api.unit import assign_unit


def _base_spatial_hierarchy(f: ifcopenshell.file) -> tuple[ifcopenshell.entity_instance, ifcopenshell.entity_instance]:
    """IfcProject → Site → Building → BuildingStorey 및 Model/Body 표현 컨텍스트."""
    project = create_entity(f, ifc_class="IfcProject", name="OpenBIM-Deflect Sample")
    assign_unit(f)

    model_ctx = add_context(f, context_type="Model")
    body_ctx = add_context(
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )

    site = create_entity(f, ifc_class="IfcSite", name="SampleSite")
    building = create_entity(f, ifc_class="IfcBuilding", name="SampleBuilding")
    storey = create_entity(f, ifc_class="IfcBuildingStorey", name="SampleStorey")

    assign_object(f, products=[site], relating_object=project)
    assign_object(f, products=[building], relating_object=site)
    assign_object(f, products=[storey], relating_object=building)

    return body_ctx, storey


def _rectangle_profile(f: ifcopenshell.file, x_mm: float, y_mm: float) -> ifcopenshell.entity_instance:
    prof = add_parameterized_profile(f, ifc_class="IfcRectangleProfileDef")
    prof.XDim = x_mm
    prof.YDim = y_mm
    prof.Position = f.createIfcAxis2Placement2D(f.createIfcCartesianPoint((0.0, 0.0)))
    return prof


def write_simple_beam(path: Path) -> None:
    """수평 방향(+X) 단순 보: 단면 200×300 mm, 경간 5000 mm (5 m, 프로젝트 길이 단위: mm)."""
    f = create_file()
    body_ctx, storey = _base_spatial_hierarchy(f)

    beam = create_entity(f, ifc_class="IfcBeam", name="SimpleBeam", predefined_type="BEAM")
    profile = _rectangle_profile(f, 200.0, 300.0)
    # 국소 Z를 전역 Y로 두고 X를 전역 X에 맞추어 익스트루전 축이 전역 +X가 되도록 함
    rep = add_profile_representation(
        f,
        context=body_ctx,
        profile=profile,
        depth=5000.0,
        placement_zx_axes=((0.0, 1.0, 0.0), (1.0, 0.0, 0.0)),
    )
    assign_representation(f, product=beam, representation=rep)
    assign_container(f, products=[beam], relating_structure=storey)

    f.write(str(path))


def _translate_matrix(x_m: float, y_m: float, z_m: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float64)
    m[0, 3] = x_m
    m[1, 3] = y_m
    m[2, 3] = z_m
    return m


def write_ten_story_four_columns_slab(path: Path) -> None:
    """10층 건물: 각 층마다 직사각형 평면에 기둥 4개(모서리) + 수평 슬래브 1장.

    - 건물 전고 약 1 m(층고 0.1 m × 10). 구 형상 비율은 구버전(층고 3 m·평면 8×6 m)과 동일하게 스케일만 1/30.
    - 각 IfcBuildingStorey의 원점은 해당 층 바닥(세계 Z = (n-1)×층고)
    - 기둥은 층 내 +Z로 한 층 높이만 익스트루드, 슬래브는 층 상면(z=층고)에 둠
    """
    n_storeys = 10
    total_height_m = 1.0
    storey_height_m = total_height_m / n_storeys
    # 구 참조(층고 3 m) 대비 비율 유지
    linear_scale = storey_height_m / 3.0
    span_x_m = 8.0 * linear_scale
    span_y_m = 6.0 * linear_scale
    col_mm = 400.0 * linear_scale
    slab_thickness_m = 0.2 * linear_scale

    f = create_file()
    project = create_entity(f, ifc_class="IfcProject", name="OpenBIM-Deflect 10-Story Sample")
    assign_unit(f)

    model_ctx = add_context(f, context_type="Model")
    body_ctx = add_context(
        f,
        context_type="Model",
        context_identifier="Body",
        target_view="MODEL_VIEW",
        parent=model_ctx,
    )

    site = create_entity(f, ifc_class="IfcSite", name="SampleSite")
    building = create_entity(f, ifc_class="IfcBuilding", name="TenStoryBuilding")
    assign_object(f, products=[site], relating_object=project)
    assign_object(f, products=[building], relating_object=site)

    # OpenBIM_Deflect Pset: 스파이크 파이프라인에서 하중·경계 힌트로 사용
    pset = add_pset(f, building, "OpenBIM_Deflect")
    edit_pset(f, pset, properties={
        "AppliedLoad_Z_N": 5000.0,
        "BoundaryMode": "FIX_MIN_Z_LOAD_MAX_Z",
    })

    storeys: list[ifcopenshell.entity_instance] = []
    for i in range(n_storeys):
        storey = create_entity(
            f,
            ifc_class="IfcBuildingStorey",
            name=f"Level {i + 1}",
        )
        assign_object(f, products=[storey], relating_object=building)
        storeys.append(storey)

    half = (col_mm / 1000.0) / 2.0
    column_xy_m = (
        (half, half),
        (span_x_m - half, half),
        (span_x_m - half, span_y_m - half),
        (half, span_y_m - half),
    )
    corner_names = ("SW", "SE", "NE", "NW")

    slab_outline_m = [
        (0.0, 0.0),
        (span_x_m, 0.0),
        (span_x_m, span_y_m),
        (0.0, span_y_m),
        (0.0, 0.0),
    ]

    for i, storey in enumerate(storeys):
        edit_object_placement(
            f,
            product=storey,
            matrix=_translate_matrix(0.0, 0.0, i * storey_height_m),
        )
        if hasattr(storey, "Elevation"):
            storey.Elevation = i * storey_height_m

        for (cx, cy), cname in zip(column_xy_m, corner_names):
            col = create_entity(
                f,
                ifc_class="IfcColumn",
                name=f"Column_L{i + 1}_{cname}",
                predefined_type="COLUMN",
            )
            profile = _rectangle_profile(f, col_mm, col_mm)
            rep = add_profile_representation(
                f,
                context=body_ctx,
                profile=profile,
                depth=storey_height_m,
                placement_zx_axes=((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
            )
            assign_representation(f, product=col, representation=rep)
            assign_container(f, products=[col], relating_structure=storey)
            edit_object_placement(f, product=col, matrix=_translate_matrix(cx, cy, 0.0))

        slab = create_entity(
            f,
            ifc_class="IfcSlab",
            name=f"Slab_L{i + 1}",
            predefined_type="FLOOR",
        )
        slab_rep = add_slab_representation(
            f,
            context=body_ctx,
            depth=slab_thickness_m,
            polyline=slab_outline_m,
        )
        assign_representation(f, product=slab, representation=slab_rep)
        assign_container(f, products=[slab], relating_structure=storey)
        edit_object_placement(
            f,
            product=slab,
            matrix=_translate_matrix(0.0, 0.0, storey_height_m),
        )

    f.write(str(path))


def write_simple_column(path: Path) -> None:
    """수직(+Z) 단순 기둥: 단면 300×300 mm, 높이 1000 mm (1 m)."""
    f = create_file()
    body_ctx, storey = _base_spatial_hierarchy(f)

    column = create_entity(f, ifc_class="IfcColumn", name="SimpleColumn", predefined_type="COLUMN")
    profile = _rectangle_profile(f, 300.0, 300.0)
    rep = add_profile_representation(
        f,
        context=body_ctx,
        profile=profile,
        depth=1000.0,
        placement_zx_axes=((0.0, 0.0, 1.0), (1.0, 0.0, 0.0)),
    )
    assign_representation(f, product=column, representation=rep)
    assign_container(f, products=[column], relating_structure=storey)

    f.write(str(path))


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    beam_path = out_dir / "simple_beam.ifc"
    column_path = out_dir / "simple_column.ifc"
    ten_story_path = out_dir / "ten_story_4columns_slab.ifc"
    write_simple_beam(beam_path)
    write_simple_column(column_path)
    write_ten_story_four_columns_slab(ten_story_path)
    print(
        f"Wrote {beam_path.name}, {column_path.name}, {ten_story_path.name} → {out_dir}",
    )


if __name__ == "__main__":
    main()
