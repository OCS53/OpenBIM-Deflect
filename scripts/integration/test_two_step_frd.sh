#!/usr/bin/env bash
# CalculiX 다중 *STEP 입력 → FRD 에 DISP 블록이 2개 이상인지 검증합니다.
# 저장소 루트에서:
#   docker compose build api
#   ./scripts/integration/test_two_step_frd.sh
#
# `api` 이미지(백엔드 Dockerfile)에 IfcOpenShell·Gmsh·CalculiX·pydantic 이 포함됩니다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose 가 필요합니다." >&2
  exit 1
fi

OUT="scripts/spike/_output/integration_two_step"

docker compose run --rm --no-deps --entrypoint "" --workdir /work api sh -c "
set -e
rm -rf ${OUT}
python3 scripts/spike/pipeline_ifc_gmsh_ccx.py \\
  --ifc sample/simple_beam.ifc \\
  --analysis-spec sample/analysis_input_v1_two_steps_example.json \\
  --run-ccx \\
  --out-dir ${OUT}
PYTHONPATH=/work/backend python3 -c \"
from pathlib import Path
from app.services.frd_extract import _find_all_block_slices
frd = Path('/work/${OUT}/model_from_pipeline.frd')
assert frd.is_file(), f'missing {frd}'
lines = frd.read_text(encoding='utf-8', errors='replace').splitlines()
n = len(_find_all_block_slices(lines, 'DISP'))
assert n >= 2, f'expected >= 2 DISP blocks in FRD, got {n}'
print('integration_two_step_frd: OK, DISP blocks =', n)
\"
"

echo "Done."
