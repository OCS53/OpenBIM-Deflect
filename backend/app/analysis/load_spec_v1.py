"""AnalysisInput v1 — docs/LOAD-MODEL-AND-INP.md

백엔드(Pydantic)와 프론트 `frontend/src/analysis/loadModel.ts` 스켈레톤 정렬:

**구현됨 (Resolver + INP)**  
- `supports[]` + `selection.type == 'min_z'`  
- `loads[]` + `type == 'nodal_force'` + `target.mode == 'rule'`  
  (`max_z_single_node`, `min_z_single_node`) 또는 `explicit` + `node_ids`  
- `loads[]` + `type == 'surface_pressure'` + `selection.kind == 'exterior'`  
  (외곽 삼각면을 등가 절점하중 `*CLOAD`로 분배; 선택 `normal_max_tilt_deg` 로 +Z 대비 **수직면(외벽)** 위주 필터)  
- `load_cases[]` 메타 + `case_id` 로 하중 그룹 → 케이스별 `*STEP`  
- `load_cases` 비어 있으면 `loads.case_id` 로 자동 생성  
- 파이프라인 `partition_ifc_elsets` 시 INP 에 IFC 부재별 `*ELSET`(해시 이름)·`ifc_elset_map.json` (로드맵 4단계 MVP)  
- `combinations[]` — 케이스별 계수 선형 중첩 → 추가 `*STEP`(등가 `*CLOAD`)
- `loads[]` + `type == 'gravity'` — C3D4 체적 질량×가속도를 **사면체당 4절점 등가 `*CLOAD`** 로 루핑
  (`material_density_kg_m3` 또는 파이프라인 `density_kg_m3` 로 밀도 [kg/m³])

**스켈레톤만 (미구현)**  
- `line_load`, `seismic_static` — 요소 타입(빔)·층별 질량·규정 범위가 선행되어야 함. 설계: `docs/LOAD-MODEL-AND-INP.md` §7.2  
- `coordinate_system` 별도 필드, 부분 지지/스프링 등
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SupportSelectionMinZ(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["min_z"] = "min_z"


class SupportRuleV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    selection: SupportSelectionMinZ
    fixed_dofs: list[int] = Field(default_factory=lambda: [1, 2, 3])


class NodalTargetRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["rule"] = "rule"
    rule: Literal["max_z_single_node", "min_z_single_node"]


class NodalTargetExplicit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["explicit"] = "explicit"
    node_ids: list[int]


class NodalForceLoadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["nodal_force"] = "nodal_force"
    id: str
    case_id: str
    target: NodalTargetRule | NodalTargetExplicit
    components: tuple[float, float, float]


class SurfacePressureSelectionExterior(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["exterior"] = "exterior"
    normal_max_tilt_deg: float | None = Field(
        default=None,
        ge=0.0,
        le=90.0,
        description=(
            "외곽면 중에서만 적용. 단위 법선과 전역 +Z 축 사이 각도 θ(0°~180°)에 대해 "
            "|θ − 90°| ≤ normal_max_tilt_deg 인 면만 압력 적용(수직 외벽 위주). "
            "미지정이면 모든 외곽면. 일부면만 쓰면 폐곡면이 아니어서 합력이 0이 아닐 수 있음."
        ),
    )


class SurfacePressureLoadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["surface_pressure"] = "surface_pressure"
    id: str
    case_id: str
    magnitude: float = Field(
        description="압력 [Pa]. +값이면 외곽면 법선 반대(내향)으로 작용.",
    )
    selection: SurfacePressureSelectionExterior


class GravityLoadV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["gravity"] = "gravity"
    id: str
    case_id: str
    acceleration: tuple[float, float, float] = Field(
        description="전역 좌표계 가속도 [m/s²] (예: (0,0,-9.81) = −Z 중력).",
    )


class LoadCaseMetaV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    category: str = "GENERAL"


class LoadCombinationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    factors: dict[str, float] = Field(
        ...,
        min_length=1,
        description="load_cases 의 case_id → 계수 (선형 중첩).",
    )


class AnalysisInputV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: Literal[1] = 1
    analysis_type: Literal["static_linear"] = "static_linear"
    load_cases: list[LoadCaseMetaV1] = Field(default_factory=list)
    supports: list[SupportRuleV1] = Field(default_factory=list)
    loads: list[NodalForceLoadV1 | SurfacePressureLoadV1 | GravityLoadV1] = Field(
        default_factory=list
    )
    combinations: list[LoadCombinationV1] = Field(default_factory=list)
    material_density_kg_m3: float | None = Field(
        default=None,
        description=(
            "중력 하중 해석 시 밀도 [kg/m³]. None 이면 파이프라인 쿼리 density_kg_m3 기본값을 사용."
        ),
    )

    @model_validator(mode="after")
    def _check_nonempty_and_load_cases(self) -> AnalysisInputV1:
        if not self.supports:
            raise ValueError("supports 가 비어 있으면 안 됩니다.")
        if not self.loads:
            raise ValueError("loads 가 비어 있으면 안 됩니다.")
        ids_from_loads = {ld.case_id for ld in self.loads}
        if not self.load_cases:
            auto = [
                LoadCaseMetaV1(id=cid, name="", category="GENERAL")
                for cid in sorted(ids_from_loads)
            ]
            return self.model_copy(update={"load_cases": auto})
        declared = {lc.id for lc in self.load_cases}
        missing = ids_from_loads - declared
        if missing:
            raise ValueError(
                "loads 의 case_id 가 load_cases 에 정의되어 있어야 합니다. "
                f"누락: {sorted(missing)}"
            )
        return self

    @model_validator(mode="after")
    def _material_density_when_gravity(self) -> AnalysisInputV1:
        has_gravity = any(isinstance(ld, GravityLoadV1) for ld in self.loads)
        if has_gravity and self.material_density_kg_m3 is not None:
            if self.material_density_kg_m3 <= 0.0:
                raise ValueError("material_density_kg_m3 는 양수여야 합니다 (중력 하중이 있을 때).")
        return self

    @model_validator(mode="after")
    def _validate_combinations(self) -> AnalysisInputV1:
        if not self.combinations:
            return self
        lc_ids = {lc.id for lc in self.load_cases}
        comb_ids: set[str] = set()
        for c in self.combinations:
            if c.id in lc_ids:
                raise ValueError(
                    f"combinations[].id 는 load_cases[].id 와 겹칠 수 없습니다: {c.id!r}"
                )
            if c.id in comb_ids:
                raise ValueError(f"combinations[].id 중복: {c.id!r}")
            comb_ids.add(c.id)
            for case_id in c.factors:
                if case_id not in lc_ids:
                    raise ValueError(
                        f"조합 {c.id!r}: 알 수 없는 case_id {case_id!r} (load_cases 에 없음)"
                    )
        return self
