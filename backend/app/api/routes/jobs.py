from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, File, HTTPException, UploadFile
from kombu.exceptions import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from app.schemas import ArtifactInfo, JobCreatedResponse, JobErrorDetail, JobStatusResponse
from app.services.frd_extract import load_fe_results_payload
from app.services.job_store import merge_job_status, read_job_status
from app.services.pipeline_runner import job_dir, list_artifact_files
from app.tasks.pipeline import run_ifc_pipeline_task

GeometryStrategy = Literal["auto", "stl_classify", "stl_raw", "occ_bbox"]

router = APIRouter()


def _ifc_header_ok(raw: bytes) -> bool:
    head = raw[:160].lstrip()
    return head.startswith(b"ISO-10303-21") or head.startswith(b"HEADER")


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
    mesh_size: float = 120.0,
    young: float = 210_000.0,
    poisson: float = 0.3,
    load_z: float = 10_000.0,
    run_ccx: bool = True,
    geometry_strategy: GeometryStrategy = "auto",
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
        },
    )

    try:
        run_ifc_pipeline_task.delay(
            job_id,
            mesh_size,
            young,
            poisson,
            load_z,
            run_ccx,
            geometry_strategy,
        )
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

    return JobStatusResponse(
        job_id=job_id,
        status=status,
        artifacts=artifacts,
        pipeline_report=pipeline_report,
        fe_results=fe_results,
        log_tail=data.get("log_tail"),
        error=error,
        celery_task_id=data.get("celery_task_id"),
    )
