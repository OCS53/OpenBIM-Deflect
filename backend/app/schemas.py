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


class FeResultsPayload(BaseModel):
    """`model_from_pipeline.frd` 에서 추출·다운샘플한 필드 (`fe_results.json` 과 동일 구조)."""

    model_config = ConfigDict(extra="ignore")

    version: Literal[1] = 1
    source: str = "calculix_frd"
    frd_basename: str = ""
    parse_error: str | None = None
    n_nodes_total_disp: int | None = None
    n_nodes_total_stress: int | None = None
    n_nodes_in_sample: int | None = None
    downsample_note: str | None = None
    displacement: FeDisplacementBlock | None = None
    stress: FeStressBlock | None = None
    magnitude: FeResultsMagnitude | None = None


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
    celery_task_id: str | None = Field(default=None, description="실행 중인 경우 Celery task id")


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
