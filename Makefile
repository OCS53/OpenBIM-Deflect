# OpenAPI 스냅샷 (docs/openapi.json) — 스키마·쿼리 변경 시 반드시 실행
.PHONY: openapi
openapi:
	@test -x .venv/bin/python3 || (echo "Create venv: python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt"; exit 1)
	.venv/bin/python3 scripts/export_openapi.py

# Docker api 이미지: 다중 *STEP FRD DISP 블록 검증 (scripts/integration/README.md)
.PHONY: integration-two-step-frd
integration-two-step-frd:
	@chmod +x scripts/integration/test_two_step_frd.sh
	@./scripts/integration/test_two_step_frd.sh
