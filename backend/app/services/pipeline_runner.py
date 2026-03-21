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
    "analysis_input.json",
    "ifc_elset_map.json",
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


def _subprocess_timeout_sec() -> int | None:
    """파이프라인 스크립트 subprocess.run timeout. None = 무제한.

    기본 86400초(24h). 예전 기본 3600(1h)은 대형 모델 동기 /analyze 가 끊기는 원인이었음.
    `PIPELINE_TIMEOUT_SEC=0` / `none` / `unlimited` 는 무제한(서버·OS 한도만 적용).
    """
    raw = os.environ.get("PIPELINE_TIMEOUT_SEC")
    if raw is None or not str(raw).strip():
        return 86400
    s = str(raw).strip().lower()
    if s in ("0", "none", "unlimited", "inf"):
        return None
    try:
        v = int(s)
    except ValueError:
        return 86400
    return v if v > 0 else None


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
    boundary_mode: str | None = None,
    first_product_only: bool = False,
    analysis_spec: dict | None = None,
    partition_ifc_elsets: bool = False,
    density_kg_m3: float = 7850.0,
) -> PipelineResult:
    root = repo_root()
    script = root / "scripts" / "spike" / "pipeline_ifc_gmsh_ccx.py"
    if not script.is_file():
        raise PipelineError(f"파이프라인 스크립트 없음: {script}")

    out = job_dir(job_id)
    out.mkdir(parents=True, exist_ok=True)
    dest_ifc = out / "input.ifc"
    try:
        shutil.copy2(source_ifc, dest_ifc)
    except shutil.SameFileError:
        # 비동기 워커: 이미 job_dir/input.ifc 를 source 로 넘김
        pass

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
        "--density-kg-m3",
        str(density_kg_m3),
        "--load-z",
        str(load_z),
    ]
    if run_ccx:
        cmd.append("--run-ccx")
    cmd.extend(["--geometry-strategy", geometry_strategy])
    if first_product_only:
        cmd.append("--first-product-only")
    if partition_ifc_elsets:
        cmd.append("--partition-ifc-elsets")
    if boundary_mode:
        cmd.extend(["--boundary-mode", boundary_mode])
    if analysis_spec is not None:
        spec_path = out / "analysis_input.json"
        spec_path.write_text(
            json.dumps(analysis_spec, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        cmd.extend(["--analysis-spec", str(spec_path)])

    timeout_sec = _subprocess_timeout_sec()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        so = e.stdout if isinstance(getattr(e, "stdout", None), str) else ""
        se = e.stderr if isinstance(getattr(e, "stderr", None), str) else ""
        lim = f"{timeout_sec}s" if timeout_sec else "무제한(비정상)"
        raise PipelineError(
            "파이프라인 하위 프로세스 시간 초과 "
            f"({lim}). PIPELINE_TIMEOUT_SEC 로 한도를 늘리거나, "
            "장시간 연산은 동기 `/api/v1/analyze` 대신 `POST /api/v1/jobs` 비동기를 사용하세요.",
            stdout=so or "",
            stderr=se or "",
        ) from e
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
    except Exception:
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
