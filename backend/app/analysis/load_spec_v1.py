"""AnalysisInput v1 — docs/LOAD-MODEL-AND-INP.md

백엔드(Pydantic)와 프론트 `frontend/src/analysis/loadModel.ts` 스켈레톤 정렬:

**구현됨 (Resolver + INP)**  
- `supports[]` + `selection.type == 'min_z'`  
- `loads[]` + `type == 'nodal_force'` + `target.mode == 'rule'`  
  (`max_z_single_node`, `min_z_single_node`) 또는 `explicit` + `node_ids`  
- `load_cases[]` 메타 + `case_id` 로 하중 그룹 → 케이스별 `*STEP`  
- `load_cases` 비어 있으면 `loads.case_id` 로 자동 생성

**스켈레톤만 (미구현)**  
- `gravity`, `surface_pressure`, `line_load`, `seismic_static`  
- `combinations[]`, `coordinate_system` 별도 필드, 부분 지지/스프링 등
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


class LoadCaseMetaV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str = ""
    category: str = "GENERAL"


class AnalysisInputV1(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: Literal[1] = 1
    analysis_type: Literal["static_linear"] = "static_linear"
    load_cases: list[LoadCaseMetaV1] = Field(default_factory=list)
    supports: list[SupportRuleV1] = Field(default_factory=list)
    loads: list[NodalForceLoadV1] = Field(default_factory=list)

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
