from __future__ import annotations

from app.celery_app import celery_app
from app.services.job_store import merge_job_status
from app.services.pipeline_runner import (
    PipelineError,
    job_dir,
    run_ifc_pipeline,
)


@celery_app.task(name="pipeline.run_ifc", bind=True, ignore_result=True)
def run_ifc_pipeline_task(
    self,
    job_id: str,
    mesh_size: float,
    young: float,
    poisson: float,
    load_z: float,
    run_ccx: bool,
    geometry_strategy: str,
    boundary_mode: str | None = None,
    first_product_only: bool = False,
    analysis_spec: dict | None = None,
) -> None:
    ifc_path = job_dir(job_id) / "input.ifc"
    if not ifc_path.is_file():
        merge_job_status(
            job_id,
            {
                "status": "failed",
                "error": {"message": "input.ifc 가 없습니다.", "log_tail": None},
            },
        )
        return

    merge_job_status(
        job_id,
        {"status": "running", "celery_task_id": getattr(self.request, "id", None)},
    )

    try:
        result = run_ifc_pipeline(
            job_id=job_id,
            source_ifc=ifc_path,
            mesh_size=mesh_size,
            young=young,
            poisson=poisson,
            load_z=load_z,
            run_ccx=run_ccx,
            geometry_strategy=geometry_strategy,
            boundary_mode=boundary_mode,
            first_product_only=first_product_only,
            analysis_spec=analysis_spec,
        )
        tail = (result.stdout + "\n" + result.stderr)[-4000:] or None
        merge_job_status(
            job_id,
            {"status": "completed", "log_tail": tail, "error": None},
        )
    except PipelineError as e:
        tail = (e.stderr or e.stdout or str(e))[-8000:] or None
        merge_job_status(
            job_id,
            {
                "status": "failed",
                "error": {"message": str(e), "log_tail": tail},
            },
        )
        raise
    except Exception as e:
        merge_job_status(
            job_id,
            {
                "status": "failed",
                "error": {"message": f"워커 내부 오류: {e}", "log_tail": None},
            },
        )
        raise
