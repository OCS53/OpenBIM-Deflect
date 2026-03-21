from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from kombu.exceptions import OperationalError
from pydantic import ValidationError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.analysis.load_spec_v1 import AnalysisInputV1
from app.schemas import ArtifactInfo, JobCreatedResponse, JobErrorDetail, JobStatusResponse
from app.services.frd_extract import load_fe_results_payload
from app.services.job_store import merge_job_status, read_job_status
from app.services.pipeline_runner import job_dir, list_artifact_files
from app.tasks.pipeline import run_ifc_pipeline_task

GeometryStrategy = Literal["auto", "stl_classify", "stl_raw", "occ_bbox"]
BoundaryMode = Literal[
    "FIX_MIN_Z_LOAD_MAX_Z",
    "FIX_MIN_Y_LOAD_MAX_Y",
    "FIX_MIN_Z_LOAD_TOP_X",
    "FIX_MIN_Z_LOAD_TOP_Y",
]

router = APIRouter()


def _ifc_header_ok(raw: bytes) -> bool:
    head = raw[:160].lstrip()
    return head.startswith(b"ISO-10303-21") or head.startswith(b"HEADER")


def _job_age_seconds(data: dict) -> float | None:
    """job_status.json 의 ISO 타임스탬프로부터 경과 초."""
    for key in ("updated_at", "created_at"):
        raw = data.get(key)
        if not isinstance(raw, str):
            continue
        try:
            s = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds()
        except ValueError:
            continue
    return None


def _report_from_disk(out: Path) -> dict | None:
    p = out / "pipeline_report.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


@router.post("/jobs", response_model=JobCreatedResponse, status_code=202)
async def create_pipeline_job(
    file: UploadFile = File(..., description="IFC SPF (.ifc)"),
    analysis_spec: str | None = Form(
        default=None,
        description="AnalysisInputV1 JSON 문자열 (선택, docs/LOAD-MODEL-AND-INP.md)",
    ),
    mesh_size: float = 0.25,
    young: float = 210_000.0,
    poisson: float = 0.3,
    load_z: float = 10_000.0,
    run_ccx: bool = True,
    geometry_strategy: GeometryStrategy = "auto",
    boundary_mode: BoundaryMode | None = None,
    first_product_only: bool = False,
) -> JobCreatedResponse:
    if not file.filename or not file.filename.lower().endswith(".ifc"):
        raise HTTPException(status_code=400, detail="파일 이름은 .ifc 로 끝나야 합니다.")

    raw = await file.read()
    if len(raw) < 32:
        raise HTTPException(status_code=400, detail="파일이 너무 작습니다.")
    if not _ifc_header_ok(raw):
        raise HTTPException(
            status_code=400,
            detail="IFC STEP Physical File(ISO-10303-21)로 보이지 않습니다.",
        )

    spec_dict: dict | None = None
    if analysis_spec is not None and analysis_spec.strip():
        try:
            parsed = json.loads(analysis_spec)
        except json.JSONDecodeError as e:
            raise HTTPException(
                status_code=400,
                detail=f"analysis_spec JSON 파싱 실패: {e}",
            ) from e
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="analysis_spec 는 JSON 객체여야 합니다.")
        try:
            AnalysisInputV1.model_validate(parsed)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=e.errors()) from e
        spec_dict = parsed

    job_id = uuid.uuid4().hex
    out = job_dir(job_id)
    out.mkdir(parents=True, exist_ok=True)
    (out / "input.ifc").write_bytes(raw)

    merge_job_status(
        job_id,
        {
            "status": "pending",
            "mesh_size": mesh_size,
            "young": young,
            "poisson": poisson,
            "load_z": load_z,
            "run_ccx": run_ccx,
            "geometry_strategy": geometry_strategy,
            "boundary_mode": boundary_mode,
            "first_product_only": first_product_only,
            "analysis_spec_used": spec_dict is not None,
        },
    )

    try:
        async_result = run_ifc_pipeline_task.delay(
            job_id,
            mesh_size,
            young,
            poisson,
            load_z,
            run_ccx,
            geometry_strategy,
            boundary_mode=boundary_mode,
            first_product_only=first_product_only,
            analysis_spec=spec_dict,
        )
        merge_job_status(job_id, {"celery_task_id": async_result.id})
    except (OperationalError, RedisConnectionError, OSError) as e:
        merge_job_status(
            job_id,
            {
                "status": "failed",
                "error": {
                    "message": f"작업 큐(Redis)에 넣지 못했습니다: {e}",
                    "log_tail": None,
                },
            },
        )
        raise HTTPException(
            status_code=503,
            detail="Redis/Celery 브로커에 연결할 수 없습니다. docker compose에 redis·worker가 있는지 확인하세요.",
        ) from e

    return JobCreatedResponse(
        job_id=job_id,
        poll_url=f"/api/v1/jobs/{job_id}",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    try:
        uuid.UUID(hex=job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="job_id는 UUID hex 여야 합니다.") from e

    root = job_dir(job_id)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")

    data = read_job_status(job_id)
    if not data:
        return JobStatusResponse(job_id=job_id, status="pending")

    raw_status = data.get("status", "pending")
    allowed: tuple[str, ...] = ("pending", "running", "completed", "failed")
    if raw_status not in allowed:
        status = cast(Literal["pending", "running", "completed", "failed"], "pending")
    else:
        status = cast(Literal["pending", "running", "completed", "failed"], raw_status)

    err_raw = data.get("error")
    error = None
    if isinstance(err_raw, dict) and err_raw.get("message"):
        error = JobErrorDetail(
            message=str(err_raw["message"]),
            log_tail=err_raw.get("log_tail"),
        )

    artifacts: list[ArtifactInfo] | None = None
    pipeline_report = None
    fe_results = None
    if status == "completed":
        artifacts = []
        for name, size in list_artifact_files(root):
            artifacts.append(
                ArtifactInfo(
                    name=name,
                    size_bytes=size,
                    url=f"/api/v1/jobs/{job_id}/artifacts/{name}",
                )
            )
        pipeline_report = _report_from_disk(root)
        fe_results = load_fe_results_payload(root)

    poll_hint: str | None = None
    age = _job_age_seconds(data) if data else None
    if status == "pending" and age is not None and age > 30.0:
        poll_hint = (
            "30초 넘게 대기(pending)입니다. Celery worker 컨테이너가 실행 중인지 확인하세요. "
            "`docker compose up api` 는 redis·worker·api 를 함께 기동합니다. "
            "동기 `POST /api/v1/analyze` 는 worker 없이 API 프로세스에서만 실행됩니다."
        )
    elif status == "running" and age is not None and age > 300.0:
        poll_hint = (
            "실행(running) 상태가 5분 넘게 지속됩니다. worker 로그·리소스를 확인하거나 "
            "PIPELINE_TIMEOUT_SEC·CELERY_TASK_TIME_LIMIT_SEC 설정을 검토하세요."
        )

    return JobStatusResponse(
        job_id=job_id,
        status=status,
        artifacts=artifacts,
        pipeline_report=pipeline_report,
        fe_results=fe_results,
        log_tail=data.get("log_tail"),
        error=error,
        celery_task_id=data.get("celery_task_id"),
        poll_hint=poll_hint,
        analysis_spec_used=data.get("analysis_spec_used"),
    )
