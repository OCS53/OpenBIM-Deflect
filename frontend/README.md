# Frontend (Vite + React)

- **IFC 뷰어:** `web-ifc-three` + Three.js, 드래그앤드롭 / 파일 선택
- **백엔드 연동:** `VITE_API_URL` 이 있으면 기본값으로 사용; 없으면 패널에 API base URL 입력
- **분석 패널:** 하중 케이스(중력·풍/지진 등가 절점·레거시 Y축), `first_product_only`, `boundary_mode` / `mesh_size` 등을 쿼리로 전달 (MVP 스텁)

## 환경 변수

`cp .env.example .env` 후 수정:

```bash
VITE_API_URL=http://localhost:8000
```

비동기 파이프라인은 Docker에서 `api`, `redis`, `worker` 를 함께 띄운 뒤 사용하세요.

## 실행

```bash
npm install
npm run dev
```

## 동기 vs 비동기

- **비동기 (기본):** `POST /api/v1/jobs` → `GET /api/v1/jobs/{id}` 폴링 → 완료 시 산출물 링크(`.frd`, `.inp` 등) 및 `pipeline_report` JSON 표시
- **동기:** `POST /api/v1/analyze` 한 번에 완료까지 대기
