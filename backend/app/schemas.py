from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ArtifactInfo(BaseModel):
    name: str
    size_bytes: int = Field(description="바이트 크기")
    url: str = Field(description="GET으로 내려받을 경로 (호스트 기준)")


class FeDisplacementBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: list[int]
    ux: list[float]
    uy: list[float]
    uz: list[float]
    x: list[float] | None = Field(
        default=None,
        description="참조 형상 좌표 (CalculiX *NODE, fe_results 작성 시 inp에서 채움)",
    )
    y: list[float] | None = None
    z: list[float] | None = None


class FeStressBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: list[int]
    sxx: list[float]
    syy: list[float]
    szz: list[float]
    sxy: list[float]
    syz: list[float]
    szx: list[float]
    von_mises: list[float]


class FeResultsMagnitude(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_abs_displacement: float | None = None
    max_von_mises: float | None = None


class FeResultsLoadStep(BaseModel):
    """다중 *STEP FRD: 케이스별 변위·응력 샘플."""

    model_config = ConfigDict(extra="ignore")

    step_index: int = Field(ge=1)
    case_id: str = ""
    name: str = ""
    displacement: FeDisplacementBlock | None = None
    stress: FeStressBlock | None = None
    magnitude: FeResultsMagnitude | None = None
    n_nodes_total_disp: int | None = None
    n_nodes_total_stress: int | None = None
    n_nodes_in_sample: int | None = None
    downsample_note: str | None = None


class FeResultsPayload(BaseModel):
    """`model_from_pipeline.frd` 에서 추출·다운샘플한 필드 (`fe_results.json` 과 동일 구조)."""

    model_config = ConfigDict(extra="ignore")

    version: Literal[1] = 1
    source: str = "calculix_frd"
    frd_basename: str = ""
    parse_error: str | None = None
    n_steps_in_frd: int | None = Field(
        default=None,
        description="FRD 내 DISP/STRESS 블록 쌍이 2개 이상일 때 스텝 수",
    )
    n_nodes_total_disp: int | None = None
    n_nodes_total_stress: int | None = None
    n_nodes_in_sample: int | None = None
    downsample_note: str | None = None
    displacement: FeDisplacementBlock | None = None
    stress: FeStressBlock | None = None
    magnitude: FeResultsMagnitude | None = None
    load_steps: list[FeResultsLoadStep] | None = Field(
        default=None,
        description="다중 CalculiX *STEP 일 때 케이스별 결과; 루트 displacement 등은 마지막 스텝",
    )


class JobErrorDetail(BaseModel):
    message: str
    log_tail: str | None = None


class JobCreatedResponse(BaseModel):
    job_id: str
    status: Literal["pending"] = "pending"
    poll_url: str = Field(description="진행 상태·결과 조회용 GET 경로 (동일 호스트 기준)")


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "running", "completed", "failed"]
    artifacts: list[ArtifactInfo] | None = Field(
        default=None,
        description="status가 completed일 때만 채워짐",
    )
    pipeline_report: dict | None = Field(
        default=None,
        description="완료 시 pipeline_report.json (실패·대기 중에는 None일 수 있음)",
    )
    fe_results: FeResultsPayload | None = Field(
        default=None,
        description="완료 시 FRD 기반 변위·응력 요약 (fe_results.json)",
    )
    log_tail: str | None = Field(default=None, description="마지막 표준출력 일부")
    error: JobErrorDetail | None = Field(default=None, description="실패 시 사유")
    celery_task_id: str | None = Field(default=None, description="큐에 넣은 뒤·실행 중 Celery task id")
    poll_hint: str | None = Field(
        default=None,
        description="pending/running 이 오래 지속될 때 원인 안내(예: worker 미기동)",
    )
    analysis_spec_used: bool | None = Field(
        default=None,
        description="제출된 AnalysisInputV1(JSON)가 파이프라인에 전달됐는지 (산출물 analysis_input.json 참고)",
    )


class AnalyzeResponse(BaseModel):
    job_id: str
    status: Literal["completed"] = "completed"
    artifacts: list[ArtifactInfo]
    pipeline_report: dict | None = Field(
        default=None,
        description="pipeline_report.json 내용 (Gmsh 전략·geometry_strategy 등)",
    )
    fe_results: FeResultsPayload | None = Field(
        default=None,
        description="FRD 기반 변위·응력 요약 (fe_results.json)",
    )
    log_tail: str | None = Field(
        default=None,
        description="파이프라인 표준출력 마지막 일부 (디버그용)",
    )
