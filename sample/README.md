# 샘플 IFC (MVP 테스트용)

**보·기둥** 단일 부재와, **10층 모듈형 건물** 샘플을 포함합니다. 파이프라인(로드 → 메쉬 → 해석) 및 뷰어 검증용입니다.

| 파일 | 설명 |
|------|------|
| `simple_beam.ifc` | 직사각형 단면 200×300 mm, 경간 5 m (5000 mm, 대략 +X 방향) |
| `simple_column.ifc` | 직사각형 단면 300×300 mm, 높이 1 m (1000 mm, +Z 방향) |
| `ten_story_4columns_slab.ifc` | 10 `IfcBuildingStorey`, 전고 약 **1 m**(층고 0.1 m). 평면·단면·슬래브는 구 8×6 m / 3 m 층고 모델을 1/30 스케일. **OpenBIM_Deflect** Pset (`AppliedLoad_Z_N` 5000 N, `BoundaryMode` FIX_MIN_Z_LOAD_MAX_Z) 포함 |

## AnalysisInputV1 JSON (API `analysis_spec`)

| 파일 | 설명 |
|------|------|
| `analysis_input_v1_example.json` | 단일 하중 케이스 |
| `analysis_input_v1_two_steps_example.json` | `load_cases` 2개 → CalculiX `*STEP` 2개, `fe_results.load_steps` |

## 재생성 방법

IfcOpenShell이 필요합니다. 저장소 루트에서:

```bash
python3 -m venv .venv
.venv/bin/pip install -r sample/requirements.txt
.venv/bin/python sample/generate_fixtures.py
```

`generate_fixtures.py`가 위 세 `.ifc` 파일을 덮어씁니다.
