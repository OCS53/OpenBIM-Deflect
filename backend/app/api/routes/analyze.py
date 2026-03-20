from __future__ import annotations

import asyncio
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.schemas import AnalyzeResponse, ArtifactInfo
from app.services.frd_extract import load_fe_results_payload
from app.services.pipeline_runner import (
    PipelineError,
    list_artifact_files,
    run_ifc_pipeline,
    safe_artifact_path,
)

GeometryStrategy = Literal["auto", "stl_classify", "stl_raw", "occ_bbox"]

router = APIRouter()


def _ifc_header_ok(raw: bytes) -> bool:
    head = raw[:160].lstrip()
    return head.startswith(b"ISO-10303-21") or head.startswith(b"HEADER")


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_ifc(
    file: UploadFile = File(..., description="IFC SPF (.ifc)"),
    mesh_size: float = 120.0,
    young: float = 210_000.0,
    poisson: float = 0.3,
    load_z: float = 10_000.0,
    run_ccx: bool = True,
    geometry_strategy: GeometryStrategy = "auto",
) -> AnalyzeResponse:
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
    with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = Path(tmp.name)

    try:
        try:
            result = await asyncio.to_thread(
                run_ifc_pipeline,
                job_id=job_id,
                source_ifc=tmp_path,
                mesh_size=mesh_size,
                young=young,
                poisson=poisson,
                load_z=load_z,
                run_ccx=run_ccx,
                geometry_strategy=geometry_strategy,
            )
        except PipelineError as e:
            tail = (e.stderr or e.stdout or str(e))[-8000:]
            raise HTTPException(
                status_code=500,
                detail={"message": str(e), "log_tail": tail},
            ) from e
    finally:
        tmp_path.unlink(missing_ok=True)

    artifacts: list[ArtifactInfo] = []
    for name, size in list_artifact_files(result.out_dir):
        artifacts.append(
            ArtifactInfo(
                name=name,
                size_bytes=size,
                url=f"/api/v1/jobs/{job_id}/artifacts/{name}",
            )
        )

    log_tail = (result.stdout + "\n" + result.stderr)[-4000:] or None
    fe_results = load_fe_results_payload(result.out_dir)
    return AnalyzeResponse(
        job_id=job_id,
        artifacts=artifacts,
        pipeline_report=result.pipeline_report,
        fe_results=fe_results,
        log_tail=log_tail,
    )


@router.get("/jobs/{job_id}/artifacts/{filename}")
async def download_artifact(job_id: str, filename: str) -> FileResponse:
    try:
        uuid.UUID(hex=job_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="job_id는 UUID hex 여야 합니다.") from e

    path = safe_artifact_path(job_id, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="파일 없음 또는 허용되지 않은 이름입니다.")
    return FileResponse(path, filename=filename, media_type="application/octet-stream")
