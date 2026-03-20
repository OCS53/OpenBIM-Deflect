"""스파이크 스크립트 `scripts/spike/pipeline_ifc_gmsh_ccx.py`를 서브프로세스로 실행."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from app.services.frd_extract import write_fe_results_json

# 파이프라인이 job 디렉터리에 쓰는 산출물 (다운로드 화이트리스트와 동일하게 유지)
PIPELINE_ARTIFACT_NAMES: tuple[str, ...] = (
    "input.ifc",
    "intermediate_from_ifc.stl",
    "volume_from_gmsh.msh",
    "model_from_pipeline.inp",
    "model_from_pipeline.frd",
    "pipeline_report.json",
    "fe_results.json",
)


class PipelineError(Exception):
    def __init__(self, message: str, *, stdout: str = "", stderr: str = ""):
        super().__init__(message)
        self.stdout = stdout
        self.stderr = stderr


def repo_root() -> Path:
    r = os.environ.get("REPO_ROOT")
    if r:
        return Path(r)
    # backend/app/services/pipeline_runner.py → repo
    return Path(__file__).resolve().parents[3]


def jobs_base_dir() -> Path:
    env = os.environ.get("JOB_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "jobs"


def job_dir(job_id: str) -> Path:
    return jobs_base_dir() / job_id


@dataclass
class PipelineResult:
    job_id: str
    out_dir: Path
    stdout: str
    stderr: str
    pipeline_report: dict | None = None


def run_ifc_pipeline(
    *,
    job_id: str,
    source_ifc: Path,
    mesh_size: float,
    young: float,
    poisson: float,
    load_z: float,
    run_ccx: bool,
    geometry_strategy: str = "auto",
) -> PipelineResult:
    root = repo_root()
    script = root / "scripts" / "spike" / "pipeline_ifc_gmsh_ccx.py"
    if not script.is_file():
        raise PipelineError(f"파이프라인 스크립트 없음: {script}")

    out = job_dir(job_id)
    out.mkdir(parents=True, exist_ok=True)
    dest_ifc = out / "input.ifc"
    shutil.copy2(source_ifc, dest_ifc)

    cmd: list[str] = [
        sys.executable,
        str(script),
        "--ifc",
        str(dest_ifc),
        "--out-dir",
        str(out),
        "--mesh-size",
        str(mesh_size),
        "--young",
        str(young),
        "--poisson",
        str(poisson),
        "--load-z",
        str(load_z),
    ]
    if run_ccx:
        cmd.append("--run-ccx")
    cmd.extend(["--geometry-strategy", geometry_strategy])

    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("PIPELINE_TIMEOUT_SEC", "3600")),
    )
    if proc.returncode != 0:
        raise PipelineError(
            f"파이프라인 종료 코드 {proc.returncode}",
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    report_path = out / "pipeline_report.json"
    report: dict | None = None
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = None

    try:
        write_fe_results_json(out)
    except OSError:
        pass

    return PipelineResult(
        job_id=job_id,
        out_dir=out,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        pipeline_report=report,
    )


def list_artifact_files(out_dir: Path) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for name in PIPELINE_ARTIFACT_NAMES:
        p = out_dir / name
        if p.is_file():
            rows.append((name, p.stat().st_size))
    return rows


def safe_artifact_path(job_id: str, filename: str) -> Path | None:
    if filename not in PIPELINE_ARTIFACT_NAMES or "/" in filename or filename.startswith("."):
        return None
    p = job_dir(job_id) / filename
    if p.is_file():
        return p
    return None
