"""작업 디렉터리에 두는 `job_status.json` — API·워커가 공유하는 비동기 작업 상태."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.pipeline_runner import job_dir


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def job_status_path(job_id: str) -> Path:
    return job_dir(job_id) / "job_status.json"


def read_job_status(job_id: str) -> dict[str, Any] | None:
    p = job_status_path(job_id)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def merge_job_status(job_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """상태 파일을 읽어 patch를 합친 뒤 원자적으로 다시 씁니다."""
    p = job_status_path(job_id)
    data: dict[str, Any] = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    now = _utc_iso()
    if "created_at" not in data and "created_at" not in patch:
        data["created_at"] = now
    data.update(patch)
    data["updated_at"] = now
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return data
