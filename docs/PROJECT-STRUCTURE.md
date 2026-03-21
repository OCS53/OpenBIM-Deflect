# 프로젝트 폴더 구조 연구 (파이프라인 기준)

본 문서는 [`OPEN-SOURCE-PIPELINE.md`](./OPEN-SOURCE-PIPELINE.md)의 **4단계**(추출 → 메쉬 → 해석 → 시각화)와 README에 적힌 **FastAPI / Celery / Redis / Docker** 구성을 맞추기 위한 **권장 모노레포 레이아웃**을 정리합니다.  
실제 디렉터리 생성은 구현 단계에서 진행하면 되고, 여기서는 **경계(책임 분리)** 와 **확장 시나리오**를 연구 목적으로 명시합니다.

---

## 1. 설계 원칙

| 원칙 | 설명 |
|------|------|
| **파이프라인 단위 모듈화** | IfcOpenShell / Gmsh / CalculiX(또는 FEniCS)는 각각 **독립 모듈**로 두고, 상위 **오케스트레이션**만 한곳에서 호출합니다. |
| **동기 API vs 비동기 작업** | HTTP는 **작업 생성·상태 조회·결과 조회**에 집중하고, 무거운 연산은 **Celery 워커**(또는 동등한 큐)로 넘깁니다. |
| **솔버는 프로세스/컨테이너 경계** | CalculiX는 **CLI 바이너리**로 두는 경우가 많아, Python에서는 **입출력 파일 생성 → 실행 → 결과 파싱** 레이어를 명확히 둡니다. |
| **프론트는 표현층** | Three.js(IFC + **해석 샘플 노드 포인트 오버랩**). (설계안) VTK.js는 풀 메쉬 필드용으로 문서에만 언급될 수 있음. |

---

## 2. 하중 모델 · INP (연구 문서)

구조화된 하중 정의, CalculiX 입력 생성, UI IA는 **[LOAD-MODEL-AND-INP.md](./LOAD-MODEL-AND-INP.md)** 에 정리합니다.  
프론트 타입 스켈레톤: `frontend/src/analysis/loadModel.ts`.

---

## 3. 파이프라인 단계 ↔ 코드 위치 매핑

[`OPEN-SOURCE-PIPELINE.md`](./OPEN-SOURCE-PIPELINE.md) 요약 표와 대응합니다.

| 파이프라인 단계 | 권장 패키지/모듈 위치 (백엔드 루트 기준) | 비고 |
|-----------------|------------------------------------------|------|
| 1. BIM 파싱·형상 추출 | `backend/app/pipeline/ifc/` | IfcOpenShell, IFC GUID·타입별 필터, (선택) 중간 STEP 등 |
| 2. 메쉬 생성 | `backend/app/pipeline/mesh/` | Gmsh Python API 또는 스크립트 생성 + 호출 |
| 3. 구조 해석 | `backend/app/pipeline/solver/` | CalculiX inp/frd 변환, 프로세스 실행, (선택) FEniCS 분기 |
| 4. 시각화 | `frontend/src/` 하위 | Three.js 장면·로더, VTK.js 결과 뷰, 공통 타입은 `packages/` 또는 `frontend/src/types/` |

**오케스트레이션(한 사이클 묶기):** `backend/app/pipeline/orchestrator.py` 또는 `backend/app/services/analysis_job.py` 등 **한 단계씩 호출**하는 서비스 레이어.

---

## 5. 권장 최상위 구조 (개요)

리포지토리 루트를 기준으로 한 **목표 스켈레톤**입니다. 이름은 팀 취향에 따라 `web` ↔ `frontend`, `api` ↔ `backend` 로 바꿀 수 있습니다.

```text
OpenBIM-Deflect/
├── README.md
├── LICENSE
├── docker-compose.yml          # pipeline-spike(현재) + (예정) API, worker, redis, frontend
├── .env.example                # 비밀·URL 플레이스홀더
│
├── docs/                       # 기존 스펙·파이프라인 문서
│   ├── MVP-v1.0-SPEC.md
│   ├── OPEN-SOURCE-PIPELINE.md
│   └── PROJECT-STRUCTURE.md    # 본 문서
│
├── scripts/
│   └── spike/                  # Docker 스파이크: toolcheck, CalculiX 최소 입력
│
├── sample/                     # MVP용 단일 부재 IFC 샘플
│
├── frontend/                   # React + Three.js (IFC + FE 포인트 오버랩)
│   ├── public/
│   ├── src/
│   │   ├── components/         # UI 패널, 레이아웃
│   │   ├── features/
│   │   │   ├── ifc-viewer/     # 드래그앤드롭, Three.js 뷰어, 피킹(부재 선택)
│   │   │   └── fea-results/   # VTK.js 히트맵, 변형 과장 슬라이더
│   │   ├── api/                # FastAPI 클라이언트(fetch, job 폴링)
│   │   └── types/              # Job ID, 변위·응력 DTO (openapi에서 생성 가능)
│   ├── package.json
│   └── Dockerfile
│
├── backend/                    # FastAPI (MVP: 스파이크 파이프라인 서브프로세스 호출)
│   ├── requirements.txt
│   ├── README.md
│   ├── data/jobs/              # 실행 시 job별 산출물 (gitignore)
│   └── app/
│       ├── main.py             # FastAPI, CORS, /health
│       ├── schemas.py
│       ├── api/routes/
│       │   └── analyze.py      # POST /analyze, GET jobs/.../artifacts
│       └── services/
│           └── pipeline_runner.py
│   # (예정) core/, pipeline/ 패키지화, Celery workers, 별도 Dockerfile 통합
│
├── docker/                     # Docker 정의
│   ├── spike/
│   │   └── Dockerfile          # 스파이크: Python + IfcOpenShell + Gmsh + CalculiX
│   └── backend/
│       └── Dockerfile          # API: 위와 동일 베이스 + FastAPI, backend·scripts·sample 복사
│
└── infra/                      # (선택) k8s, compose 오버레이, CI
    └── README.md
```

### 3.1 런타임 작업 디렉터리 (git에 넣지 않음)

해석은 **임시 파일**이 많습니다. 예시:

```text
# .gitignore 대상 (경로만 관례)
backend/data/uploads/           # 업로드된 IFC
backend/data/jobs/{job_id}/     # 중간: brep/msh/inp/frd, 로그
```

`app/storage/` 모듈에서 위 경로를 **환경변수**로 받아 일관되게 쓰면, Docker 볼륨 마운트와 로컬 개발이 같아집니다.

---

## 6. API·작업 흐름과 폴더의 관계

시나리오([`OPEN-SOURCE-PIPELINE.md`](./OPEN-SOURCE-PIPELINE.md) § 시나리오)를 서버 측으로 옮기면 대략 다음입니다.

1. **POST** 업로드 / 또는 presigned 업로드 → `api/routes/upload.py` → `storage`에 IFC 저장  
2. **POST** `jobs` (부재 GUID, 하중, 지지) → DB 또는 Redis에 job 상태 → Celery `workers/tasks.py` 큐잉  
3. 워커가 `pipeline/ifc` → `mesh` → `solver` 순 실행, 결과를 JSON(+선택 바이너리)으로 `jobs/{id}/out/`  
4. **GET** `jobs/{id}` / `jobs/{id}/result` → 프론트 `features/fea-results`가 VTK.js·Three.js로 소비  

MVP에서는 **인메모리 job store + 파일시스템**만으로도 시작 가능하며, 폴더 구조는 위와 동일하게 두고 **저장소 구현체만** 나중에 교체하면 됩니다.

---

## 7. 솔버·도구 의존성 배치

| 구성 요소 | 일반적인 배치 |
|-----------|----------------|
| **CalculiX 바이너리** | `backend` Docker 이미지에 설치, 또는 별도 `solver` 서비스 컨테이너에서 공유 볼륨으로 inp/frd 교환 |
| **Gmsh** | Python 패키지 + 시스템 라이브러리를 동일 `backend`/`worker` 이미지에 포함하는 방식이 단순 |
| **IfcOpenShell** | `backend` 및 `worker` 이미지 모두에 설치 (워커만 파이프라인 실행 시) |

**워커 분리:** `docker-compose`에서 `api`와 `worker`가 **같은 이미지**를 쓰되 command만 `celery`로 다르게 하는 패턴이 MVP에 흔합니다.

---

## 8. 프론트엔드 세분화 이유

| 영역 | 라이브러리 | 폴더 아이디어 |
|------|------------|----------------|
| IFC 로드·피킹 | Three.js (+ ifc.js 등 로더가 도입되면 해당 래퍼) | `features/ifc-viewer/` |
| 변위·응력 필드 | VTK.js | `features/fea-results/` |
| 공통 UI | React | `components/` |

이렇게 나누면 README의 **「Three.js로 장면, VTK.js로 필드」** 분업이 코드 탐색에도 그대로 반영됩니다.

---

## 9. 다음 단계 (구현 시)

1. 위 **최상위 구조**대로 빈 디렉터리·최소 `README` 또는 패키지 초기화만 추가  
2. `docker-compose.yml`에 **redis + api + worker + frontend** 최소 서비스 정의  
3. `pipeline/`에 **스텁 함수**(입력 IFC 경로 → 더미 메쉬 → 더미 결과)로 E2E 배선  
4. [`MVP-v1.0-SPEC.md`](./MVP-v1.0-SPEC.md) 완료 기준에 맞춰 단계별로 실제 IfcOpenShell / Gmsh / CalculiX 연결  

---

## 관련 문서

- 파이프라인 4단계·도구: [`OPEN-SOURCE-PIPELINE.md`](./OPEN-SOURCE-PIPELINE.md)
- MVP 범위: [`MVP-v1.0-SPEC.md`](./MVP-v1.0-SPEC.md)
- 프로젝트 소개: [`README.md`](../README.md)
