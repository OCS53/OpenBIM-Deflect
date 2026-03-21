# HTTP API (MVP 뼈대)

FastAPI 앱은 `backend/app` 에 있으며, Docker 서비스 `api` 로 실행합니다.

## 시간 한도 (동기 `/analyze` 가 약 60분에 끊길 때)

- **`PIPELINE_TIMEOUT_SEC`**: `run_ifc_pipeline` 이 스파이크 스크립트를 `subprocess.run(..., timeout=…)` 으로 실행할 때의 초 단위 한도. **기본 86400(24h)**. 예전 기본 **3600(1h)** 에서 정확히 1시간 후 `Failed to fetch` 또는 500 이 났다면 이 값이 원인이었을 수 있습니다.
- **`0` / `none` / `unlimited`**: subprocess 타임아웃 없음(서버·OS 한도만 적용).
- **`CELERY_TASK_TIME_LIMIT_SEC`**: Celery 작업 하드 리밋(초). **기본 86400**. 비동기 `/jobs` 가 조기 종료될 때 확인.
- Docker Compose 의 `api`·`worker` 서비스에 위 변수가 명시되어 있으면 그 값이 우선합니다.

장시간 연산은 브라우저 탭을 열어 둔 채 **동기** 요청보다 **`POST /api/v1/jobs`** 폴링이 안전합니다.

## 기동

```bash
docker compose up --build api redis worker
```

- **동기** 해석만 쓸 때는 `api`만 띄워도 됩니다 (`POST /api/v1/analyze`).
- **비동기** 큐(`POST /api/v1/jobs`)를 쓰려면 **redis + worker** 가 함께 있어야 합니다.

개발 시(코드 마운트·자동 리로드):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build api redis worker
```

## 문서

- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **런타임 OpenAPI JSON:** [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)
- **저장소 계약(스냅샷):** [`openapi.json`](openapi.json) — 코드와 PR 리뷰용으로 버전 관리합니다.

### `openapi.json` 갱신 (필수)

`geometry_strategy`, `pipeline_report`, `AnalyzeResponse` 등 **요청/응답 스키마**나 쿼리 파라미터를 바꾼 커밋에는 아래를 함께 실행해 [`openapi.json`](openapi.json)을 맞춥니다.

```bash
make openapi
```

(최초 1회) `python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt`

## 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 |
| POST | `/api/v1/analyze` | IFC 업로드 + 파이프라인 **동기** 실행 (응답까지 대기) |
| POST | `/api/v1/jobs` | IFC 업로드 후 Celery 큐에 넣음 → **202** + `job_id` (Redis·worker 필요) |
| GET | `/api/v1/jobs/{job_id}` | 작업 상태·완료 시 `artifacts`·`pipeline_report` |
| GET | `/api/v1/jobs/{job_id}/artifacts/{filename}` | 산출물 다운로드 |

### `POST /api/v1/analyze`

- **본문:** `multipart/form-data`
  - **`file`**: `.ifc` (필수)
  - **`analysis_spec`** (선택): **AnalysisInputV1** 전체를 JSON **문자열**로 넣은 필드. 지정 시 파이프라인이 구조화 스펙으로 CalculiX INP 를 생성하고, 작업 폴더에 `analysis_input.json` 이 남습니다. 스키마는 [`LOAD-MODEL-AND-INP.md`](LOAD-MODEL-AND-INP.md), 예시는 [`sample/analysis_input_v1_example.json`](../sample/analysis_input_v1_example.json). 잘못된 JSON·검증 실패 시 **400**.
- **쿼리 (선택):** `mesh_size`, `young`, `poisson`, **`density_kg_m3`** (기본 7850, AnalysisInputV1 `gravity` 시 스펙에 `material_density_kg_m3` 없으면 사용), `load_z`, `run_ccx`, **`geometry_strategy`**, **`boundary_mode`**, **`first_product_only`**
  - **`boundary_mode`**: 미지정이면 IFC Pset·기본(`FIX_MIN_Z_LOAD_MAX_Z`). 값: `FIX_MIN_Z_LOAD_MAX_Z` | `FIX_MIN_Y_LOAD_MAX_Y` | `FIX_MIN_Z_LOAD_TOP_X` | `FIX_MIN_Z_LOAD_TOP_Y` (수평은 Z 최대 노드에 단일 절점 스텁).
  - **`first_product_only`**: `true` 이면 구조 부재 중 **첫 요소만** 메쉬 (단일 부재 검증).
  - **`mesh_size`:** Gmsh 특성 길이 상한. IfcOpenShell로 나온 **모델 좌표 단위와 동일**해야 함(일반적으로 **m**; 기본 `0.25`). 과거 기본값 `120`은 m 좌표에서 “120 m 셀”로 해석되어 거칠거나 혼동을 줄 수 있었음.
  - `auto` — **정점 AABB 체적 메쉬를 먼저** 시도(빠름). 실패 시 `classifySurfaces` 여러 각도 → raw STL → OCC bbox 폴백 (기본)
  - `stl_classify` — classify 단계만 (실패 시 오류, bbox 없음)
  - `stl_raw` — merge + `createGeometry` 만 (실패 시 오류)
  - `occ_bbox` — STL 생략, IFC 정점 바운딩 박스만

응답 JSON에 **`pipeline_report`** 가 포함되면, 실제로 쓰인 Gmsh 전략은 `gmsh_volume_strategy` 필드를 보면 됩니다.

### `POST /api/v1/jobs` (비동기)

- **본문·쿼리:** `POST /analyze` 와 동일 (`multipart` 필드 `file`, 선택 쿼리 `mesh_size`, `young`, …).
- **응답:** **202 Accepted**, 본문에 `job_id`, `poll_url` (`GET /api/v1/jobs/{job_id}`).
- 브로커 연결 실패 시 **503** (Redis 미기동 등).
- 상태는 작업 디렉터리의 **`job_status.json`** 에도 기록됩니다 (`pending` → `running` → `completed` | `failed`).

### `GET /api/v1/jobs/{job_id}`

- `status`: `pending` | `running` | `completed` | `failed`
- `completed` 이면 `artifacts`, `pipeline_report` 채움 (동기 `/analyze` 와 동일한 URL 규칙).
- **`fe_results`**: `model_from_pipeline.frd` 에서 읽은 **노드 변위(DISP)·응력(STRESS)** 요약. 작업 폴더의 `fe_results.json` 과 동일하며, 노드가 많으면 **균등 다운샘플**됩니다. 상한은 환경 변수 **`FE_RESULTS_MAX_NODES`** (기본 2500).
  - `displacement`: `node_id`, `ux`, `uy`, `uz` (샘플된 노드만). 선택적으로 `x`, `y`, `z` (INP *NODE 참조 좌표, VTK 시각화용).
  - `stress`: `sxx`…`szx`, `von_mises` (노드에 보간된 값; STRESS 블록이 있을 때만)
  - `magnitude`: 전체 FRD 기준 `max_abs_displacement`, `max_von_mises`
  - **다중 하중 케이스** (`AnalysisInputV1` 에 서로 다른 `case_id`로 `*STEP`이 여러 개인 경우): `load_steps` 배열에 스텝별 동일 구조(`step_index`, `case_id`, `name`, `displacement`, …)가 들어갑니다. 루트의 `displacement`/`stress`/`magnitude`는 **마지막 스텝** 기준(기존 VTK 패널 호환). `analysis_input.json` 이 있으면 `case_id`·이름을 여기에 맞춥니다.
  - `n_steps_in_frd`: 위 다중 스텝일 때 FRD에서 읽은 스텝 수.
- `failed` 이면 `error.message`, `error.log_tail`.
- **`analysis_spec_used`**: 생성 시 `analysis_spec` 를 넘겼으면 `true`, 아니면 `false` 또는(구 작업) 생략.
- **`poll_hint`**: `pending` 이 30초 넘게 지속되거나 `running` 이 과도하게 길 때, 원인 추정 안내(예: Celery worker 미기동). `docker compose up api` 는 `redis`·`worker`·`api` 를 함께 기동합니다.

### 예시

```bash
curl -sS -X POST "http://localhost:8000/api/v1/analyze?geometry_strategy=auto&run_ccx=true" \
  -F "file=@sample/simple_beam.ifc" | python3 -m json.tool
```

비동기 작업 생성 후 폴링 (응답의 `job_id`로 `GET` 반복):

```bash
curl -sS -X POST "http://localhost:8000/api/v1/jobs?run_ccx=true" \
  -F "file=@sample/simple_beam.ifc" | python3 -m json.tool
# → job_id 복사 후
curl -sS "http://localhost:8000/api/v1/jobs/<job_id>" | python3 -m json.tool
```

## 산출물

Job 디렉터리(`backend/data/jobs/{job_id}/`)에 예를 들어 다음이 생깁니다.

- `input.ifc`, `intermediate_from_ifc.stl`, `volume_from_gmsh.msh`
- `model_from_pipeline.inp`, `model_from_pipeline.frd` (ccx 실행 시)
- `ifc_elset_map.json` — `partition_ifc_elsets=true` 일 때 ELSET ↔ IFC GlobalId 요약
- **`pipeline_report.json`** — 요청한 `geometry_strategy` 와 실제 `gmsh_volume_strategy` 외:
  - `n_structural_products`: 병합한 IFC 구조 부재 수
  - `ifc_applied_load_z_n`: 실제 사용된 절점 하중 [N]
  - `bc_mode`: `FIX_MIN_Z_LOAD_MAX_Z` | `FIX_MIN_Y_LOAD_MAX_Y` | `FIX_MIN_Z_LOAD_TOP_X` | `FIX_MIN_Z_LOAD_TOP_Y`
  - `ifc_load_from_pset`, `ifc_bc_from_pset`: IFC Pset에서 읽었는지 여부

다운로드는 화이트리스트에 있는 파일명만 허용합니다.

## IFC Pset `OpenBIM_Deflect` (스파이크 파이프라인)

스파이크 파이프라인(`scripts/spike/pipeline_ifc_gmsh_ccx.py`)은 **IfcProject / IfcSite / IfcBuilding** 중 하나에 붙은 Pset **`OpenBIM_Deflect`** 를 읽어 하중·경계 힌트로 사용합니다.

| 속성 | 타입 | 설명 |
|------|------|------|
| `AppliedLoad_Z_N` | 실수 | 절점 하중 크기 [N]. 미설정 시 CLI 기본값 |
| `BoundaryMode` | 문자열 | `FIX_MIN_Z_LOAD_MAX_Z`, `FIX_MIN_Y_LOAD_MAX_Y`, `FIX_MIN_Z_LOAD_TOP_X`, `FIX_MIN_Z_LOAD_TOP_Y` (수평 모드는 최소 Z 고정·Z 최대 노드에 수평 dof) |

HTTP 쿼리 `boundary_mode`·CLI `--boundary-mode` / `--load-z` 가 Pset보다 우선합니다. 스파이크 직접 실행 시 `--first-product-only` 로 구조 부재 중 첫 요소만 사용. 예시는 `sample/ten_story_4columns_slab.ifc` (생성 시 `generate_fixtures.py` 에서 Pset 부여).
