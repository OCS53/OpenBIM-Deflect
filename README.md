# 🏗️ OpenBIM-Deflect

[License: MIT](https://opensource.org/licenses/MIT)
[PRs Welcome](http://makeapullrequest.com)

**OpenBIM-Deflect**는 건축 정보 모델(BIM, IFC 포맷)을 웹 브라우저로 불러와 물리적 하중을 가하고, 구조물의 휘어짐(Deflection)과 응력(Stress)을 실시간으로 테스트할 수 있는 **오픈소스 웹 기반 구조 해석 시뮬레이터**입니다.

## 💡 왜 이 프로젝트를 시작했나요? (Motivation)

건축 및 엔지니어링 업계에서 BIM 데이터를 구조 해석에 활용하려면, 수천만 원에 달하는 무거운 상용 소프트웨어(CAE)와 복잡한 데이터 변환 과정이 필요합니다. 
우리는 "**누구나 웹 브라우저에서 클릭 몇 번만으로 BIM 모델의 구조적 안정성을 직관적으로 시각화해 볼 수 없을까?**"라는 질문에서 출발했습니다. 비싼 프로그램 설치 없이, 누구나 접근 가능한 구조 해석의 민주화를 목표로 합니다.

## ✨ 주요 기능 (Features) - MVP v1.0

- **Drag & Drop IFC 로더:** `.ifc` 파일을 브라우저에 던져넣기만 하면 3D 환경에 렌더링됩니다.
- **직관적인 하중 테스트:** 테스트하고 싶은 부재(기둥, 보 등)를 클릭하고 하중(kN)과 방향을 UI에서 바로 입력합니다.
- **클라우드 기반 FEA 연산:** 백엔드에서 자동으로 형상을 추출하고 메쉬를 생성하여 구조 해석(FEA)을 수행합니다.
- **히트맵 시각화 (Heatmap Visualization):** 연산이 완료되면 휘어진(Deflected) 모습과 응력이 집중된 구간을 3D 컬러 히트맵으로 보여줍니다.

## 🛠️ 기술 스택 (Tech Stack)

OpenBIM-Deflect는 최신 오픈소스 라이브러리들을 파이프라인으로 연결하여 구축되었습니다.

### Frontend

- **React** / **Vite** / **Three.js r149** + **web-ifc-three** (로컬 IFC 미리보기 뷰어)
- **VTK.js** (`fe_results` 샘플 노드: von Mises 또는 |변위| 포인트 필드)

### Backend (Analysis Pipeline)

- **FastAPI** (비동기 API 서버 및 작업 오케스트레이션)
- **IfcOpenShell** (IFC 솔리드 형상 및 메타데이터 추출)
- **Gmsh** (유한요소해석용 3D 메쉬 생성기)
- **CalculiX** (오픈소스 구조 해석 솔버 엔진)
- **Celery / Redis** (무거운 연산 작업을 위한 비동기 큐 대기열)

## 🚀 시작하기 (Getting Started)

### 사전 요구 사항 (Prerequisites)

- Docker 및 Docker Compose (가장 권장되는 실행 방법)

한 번에 API·Redis·Celery worker·프론트(Vite)를 띄우려면 저장소 루트에서:

```bash
./start.sh
```

개발용(코드 마운트·API `--reload`): `./start.sh --dev` · API만: `./start.sh --api-only` · 백그라운드: `./start.sh -d`

다중 하중 케이스 FRD 검증(Docker, 수 분 소요): `docker compose build api` 후 `make integration-two-step-frd` 또는 `./scripts/integration/test_two_step_frd.sh` ([`scripts/integration/README.md`](scripts/integration/README.md)).

### 파이프라인 스파이크 (IfcOpenShell + Gmsh + CalculiX)

MVP 본구현 전에 **한 이미지**에서 도구 체인을 맞춰 보려면:

```bash
docker compose build pipeline-spike
docker compose run --rm pipeline-spike
```

상세·대화형 셸: `[scripts/spike/README.md](scripts/spike/README.md)`

### API 서버 (FastAPI, MVP 뼈대)

IFC 업로드 → 스파이크 파이프라인 실행 → 산출물 URL 응답.

- **동기:** `POST /api/v1/analyze` — Redis 없이 `api` 만으로 가능  
  ```bash
  docker compose up --build api
  ```
- **비동기 (Celery + Redis):** `POST /api/v1/jobs` → `GET /api/v1/jobs/{id}` 폴링  
  ```bash
  docker compose up --build api
  ```
  (`api` 서비스가 `redis`·`worker`에 `depends_on` 되어 있어 함께 기동됩니다. worker 없이 API만 켜 두면 작업이 `pending`에서 끝나지 않습니다.)
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)  
- 상세: `[backend/README.md](backend/README.md)` · `[docs/API.md](docs/API.md)` · 하중·INP·UI 연구: `[docs/LOAD-MODEL-AND-INP.md](docs/LOAD-MODEL-AND-INP.md)`  
- API 계약 스냅샷: `[docs/openapi.json](docs/openapi.json)` — 스키마 변경 후 `make openapi` 로 재생성

### 로컬 환경에서 실행하기 (현재 가능한 것)

1. 클론
  ```bash
   git clone https://github.com/OCS53/OpenBIM-Deflect.git
   cd OpenBIM-Deflect
  ```
2. **API + 파이프라인** (프론트·Redis·Celery 없이 동기 1경로)
  ```bash
   docker compose up --build api
  ```
  - API 문서: [http://localhost:8000/docs](http://localhost:8000/docs)  
  - 개발용(소스 마운트·reload): `docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build api`  
  - 비동기까지: `docker compose up api` 만으로도 redis·worker·api 가 함께 뜹니다(명시적으로 `redis worker`를 더할 필요 없음).
3. **CLI 스파이크** (저장소 전체 마운트)
  ```bash
   docker compose run --rm pipeline-spike
   # 또는
   docker compose run --rm pipeline-spike python3 scripts/spike/pipeline_ifc_gmsh_ccx.py --ifc sample/simple_beam.ifc --run-ccx
  ```
4. **IFC 뷰어 + API 패널** — `sample/*.ifc` 드래그앤드롭, `VITE_API_URL` 로 파이프라인 동기/비동기 실행·산출물 다운로드
  ```bash
   cp frontend/.env.example frontend/.env   # VITE_API_URL=http://localhost:8000
   cd frontend && npm install && npm run dev
  ```
  - 브라우저: [http://localhost:5173](http://localhost:5173)  
  - Docker: `docker compose up frontend` (`VITE_API_URL` 은 compose에 기본값)  
  - 상세: `[frontend/README.md](frontend/README.md)`

> 해석 완료 후 **분석 패널**에 VTK 뷰가 나타납니다(백엔드가 `displacement`에 `x,y,z` 를 붙인 경우). Redis/Celery 비동기 작업은 `POST /api/v1/jobs` 로 사용 가능합니다. `[docs/PROJECT-STRUCTURE.md](docs/PROJECT-STRUCTURE.md)` 참고.

---

## 🗺️ 로드맵 (Roadmap)

[✓] 프로젝트 아키텍처 및 파이프라인 설계  
[✓] MVP 개발: 단순 단일 부재(Beam/Column) 대상 정적 하중 해석 파이프라인 구축  
[✓] 다중 부재 병합 메쉬·IFC Pset(`OpenBIM_Deflect`) 하중/경계 힌트 (스파이크 파이프라인)  
[✓] 복합 구조물·하중 UI (단일 부재 옵션, 풍/지진 **등가 절점 스텁**, API `boundary_mode`) — 스펙트럼·조합은 미구현  
[ ] 해양 구조물 / 선박(Ship Hull) 등 범용 3D 부재로의 포맷(.step) 확장 지원

## 🤝 기여하기 (Contributing)

구조 엔지니어, 3D 웹 개발자, 오픈소스 애호가 등 누구의 기여든 환영합니다! 버그 리포트, 기능 제안, Pull Request 모두 자유롭게 남겨주세요. 자세한 내용은 CONTRIBUTING.md를 참고해 주세요.

## 📄 라이선스 (License)

이 프로젝트는 MIT License에 따라 배포됩니다.