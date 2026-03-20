#!/usr/bin/env python3
"""
FastAPI OpenAPI 스키마를 docs/openapi.json 으로 덤프합니다.

다음을 변경한 뒤에는 **반드시** 다시 실행해 저장소 계약과 코드를 맞춥니다.

- geometry_strategy, pipeline_report, AnalyzeResponse 등 API 스키마/쿼리
- backend/app 의 라우트·모델

실행 (저장소 루트):

    make openapi
    # 또는
    .venv/bin/python3 scripts/export_openapi.py
    # (의존성) pip install -r backend/requirements.txt
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402


def main() -> None:
    out = ROOT / "docs" / "openapi.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote", out)


if __name__ == "__main__":
    main()
