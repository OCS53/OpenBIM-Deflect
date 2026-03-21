# OpenBIM-Deflect API (MVP 뼈대)

FastAPI로 IFC 파일을 받아 [`scripts/spike/pipeline_ifc_gmsh_ccx.py`](../scripts/spike/pipeline_ifc_gmsh_ccx.py)를 서브프로세스로 실행합니다.  
무거운 연산은 **Celery + Redis** 로 분리할 수 있습니다 (`POST /api/v1/jobs` → `GET /api/v1/jobs/{id}`).  
CalculiX·Gmsh·IfcOpenShell이 **API·worker 이미지**에 포함되어 있으므로 **Docker** 실행을 권장합니다.

## 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/health` | 헬스체크 |
| POST | `/api/v1/analyze` | 동기: 업로드 후 응답까지 파이프라인 완료 |
| POST | `/api/v1/jobs` | 비동기: **202** + `job_id` (Redis·Celery worker 필요) |
| GET | `/api/v1/jobs/{job_id}` | `pending` / `running` / `completed` / `failed` 조회 |
| GET | `/api/v1/jobs/{job_id}/artifacts/{filename}` | 산출물 다운로드 (화이트리스트 파일명만) |

`POST /api/v1/analyze` 및 `POST /api/v1/jobs` 공통 쿼리(선택): `mesh_size`, `young`, `poisson`, `load_z`, `run_ccx`, **`geometry_strategy`**, **`boundary_mode`**, **`first_product_only`**.  
완료 응답의 **`pipeline_report`** 에 실제 Gmsh 전략(`gmsh_volume_strategy`)이 들어갑니다.  
`run_ccx=true` 이고 FRD에 DISP/STRESS가 있으면 **`fe_results`**(변위·응력 요약, `fe_results.json` 과 동일)가 포함됩니다. 노드 상한은 **`FE_RESULTS_MAX_NODES`** (기본 2500).

환경 변수:

- `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` (기본 `redis://localhost:6379/0`)
- **`PIPELINE_TIMEOUT_SEC`**: 동기 `/analyze` 및 워커 내 subprocess 한도(초). 기본 **86400**(24h). `0`/`none`/`unlimited` = 무제한.
- **`CELERY_TASK_TIME_LIMIT_SEC`**: Celery 하드 타임아웃(초). 기본 **86400**.

전체 설명: [`docs/API.md`](../docs/API.md)

스키마(`geometry_strategy`, `pipeline_report` 등)를 고친 뒤에는 저장소 루트에서 **`make openapi`** 로 [`docs/openapi.json`](../docs/openapi.json)을 갱신합니다.

## Docker (저장소 루트)

```bash
docker compose up --build api
# OpenAPI: http://localhost:8000/docs
# (compose 에서 api 가 redis·worker 에 depends_on — 비동기 /jobs 도 동일 명령으로 가능)
```

동기 `/analyze` 만 쓰고 worker 를 띄우기 싫다면, 로컬에서 uvicorn 만 실행하거나 compose 를 커스텀하세요.

소스 마운트 + `--reload` (비동기까지 쓰려면 worker·redis 포함):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build api redis worker
```

워커만 별도 터미널에서 (로컬 venv):

```bash
cd backend && CELERY_BROKER_URL=redis://localhost:6379/0 celery -A app.celery_app worker --loglevel=info
```

## 예시 (curl)

```bash
curl -sS -X POST "http://localhost:8000/api/v1/analyze?mesh_size=0.25&young=210000" \
  -F "file=@sample/simple_beam.ifc" | python3 -m json.tool
```

응답의 `artifacts[].url`로 `.frd` 등을 추가 요청합니다.

## 데이터 디렉터리

기본: `backend/data/jobs/{job_id}/` (`.gitignore`).  
컨테이너에서는 볼륨 `api_job_data`에 저장됩니다.
