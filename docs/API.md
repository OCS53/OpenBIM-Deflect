# HTTP API (MVP 뼈대)

FastAPI 앱은 `backend/app` 에 있으며, Docker 서비스 `api` 로 실행합니다.

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

- **본문:** `multipart/form-data`, 필드 `file` = `.ifc`
- **쿼리 (선택):** `mesh_size`, `young`, `poisson`, `load_z`, `run_ccx`, **`geometry_strategy`**
  - `auto` — Gmsh `classifySurfaces` 여러 각도 → raw STL → 실패 시 OCC bbox (기본)
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
  - `displacement`: `node_id`, `ux`, `uy`, `uz` (샘플된 노드만)
  - `stress`: `sxx`…`szx`, `von_mises` (노드에 보간된 값; STRESS 블록이 있을 때만)
  - `magnitude`: 전체 FRD 기준 `max_abs_displacement`, `max_von_mises`
- `failed` 이면 `error.message`, `error.log_tail`.

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
- **`pipeline_report.json`** — 요청한 `geometry_strategy` 와 실제 `gmsh_volume_strategy` 등

다운로드는 화이트리스트에 있는 파일명만 허용합니다.
