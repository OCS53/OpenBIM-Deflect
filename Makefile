# OpenAPI 스냅샷 (docs/openapi.json) — 스키마·쿼리 변경 시 반드시 실행
.PHONY: openapi
openapi:
	@test -x .venv/bin/python3 || (echo "Create venv: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"; exit 1)
	.venv/bin/python3 scripts/export_openapi.py
