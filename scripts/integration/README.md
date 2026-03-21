# 통합 검증 스크립트

## `test_two_step_frd.sh`

`AnalysisInputV1` 두 하중 케이스(`sample/analysis_input_v1_two_steps_example.json`)로 파이프라인·CalculiX 를 실행한 뒤, 생성된 `.frd` 안에 **DISP 블록이 2개 이상** 있는지 확인합니다.

```bash
docker compose build api
./scripts/integration/test_two_step_frd.sh
```

(`openbim-deflect-api` 이미지에 스파이크 파이프라인과 pydantic 이 포함됩니다. 소스 마운트 없이 이미지에 빌드 시점 코드가 들어가므로, 로컬 변경 후에는 `docker compose build api` 를 다시 실행하세요.)

산출물은 `scripts/spike/_output/integration_two_step/` 에 쓰이며, `_output/` 은 `.gitignore` 됩니다.
