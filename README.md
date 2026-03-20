# 🏗️ OpenBIM-Deflect

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)

**OpenBIM-Deflect**는 건축 정보 모델(BIM, IFC 포맷)을 웹 브라우저로 불러와 물리적 하중을 가하고, 구조물의 휘어짐(Deflection)과 응력(Stress)을 실시간으로 테스트할 수 있는 **오픈소스 웹 기반 구조 해석 시뮬레이터**입니다.



## 💡 왜 이 프로젝트를 시작했나요? (Motivation)
건축 및 엔지니어링 업계에서 BIM 데이터를 구조 해석에 활용하려면, 수천만 원에 달하는 무거운 상용 소프트웨어(CAE)와 복잡한 데이터 변환 과정이 필요합니다. 
우리는 **"누구나 웹 브라우저에서 클릭 몇 번만으로 BIM 모델의 구조적 안정성을 직관적으로 시각화해 볼 수 없을까?"**라는 질문에서 출발했습니다. 비싼 프로그램 설치 없이, 누구나 접근 가능한 구조 해석의 민주화를 목표로 합니다.

## ✨ 주요 기능 (Features) - MVP v1.0
- **Drag & Drop IFC 로더:** `.ifc` 파일을 브라우저에 던져넣기만 하면 3D 환경에 렌더링됩니다.
- **직관적인 하중 테스트:** 테스트하고 싶은 부재(기둥, 보 등)를 클릭하고 하중(kN)과 방향을 UI에서 바로 입력합니다.
- **클라우드 기반 FEA 연산:** 백엔드에서 자동으로 형상을 추출하고 메쉬를 생성하여 구조 해석(FEA)을 수행합니다.
- **히트맵 시각화 (Heatmap Visualization):** 연산이 완료되면 휘어진(Deflected) 모습과 응력이 집중된 구간을 3D 컬러 히트맵으로 보여줍니다.

## 🛠️ 기술 스택 (Tech Stack)
OpenBIM-Deflect는 최신 오픈소스 라이브러리들을 파이프라인으로 연결하여 구축되었습니다.

### Frontend
- **React.js** / **Three.js** (웹 3D 렌더링 및 UI)
- **VTK.js** (해석 결과 3D 히트맵 시각화)

### Backend (Analysis Pipeline)
- **FastAPI** (비동기 API 서버 및 작업 오케스트레이션)
- **IfcOpenShell** (IFC 솔리드 형상 및 메타데이터 추출)
- **Gmsh** (유한요소해석용 3D 메쉬 생성기)
- **CalculiX** (오픈소스 구조 해석 솔버 엔진)
- **Celery / Redis** (무거운 연산 작업을 위한 비동기 큐 대기열)

## 🚀 시작하기 (Getting Started)

### 사전 요구 사항 (Prerequisites)
- Docker 및 Docker Compose (가장 권장되는 실행 방법)

### 로컬 환경에서 실행하기
1. 리포지토리를 클론합니다.
   ```bash
   git clone [https://github.com/your-username/OpenBIM-Deflect.git](https://github.com/your-username/OpenBIM-Deflect.git)
   cd OpenBIM-Deflect

2. Docker Compose를 사용해 전체 스택(Frontend, Backend, Solver, Redis)을 실행합니다.

   ```bash
   docker-compose up --build
브라우저에서 http://localhost:3000으로 접속하여 시뮬레이터를 사용해 보세요!

🗺️ 로드맵 (Roadmap)
[x] 프로젝트 아키텍처 및 파이프라인 설계
[ ] MVP 개발: 단순 단일 부재(Beam/Column) 대상 정적 하중 해석 파이프라인 구축
[ ] 다중 부재 및 복합 구조물 해석 지원
[ ] 다양한 하중 조건(풍하중, 지진하중 등) 추가
[ ] 해양 구조물 / 선박(Ship Hull) 등 범용 3D 부재로의 포맷(.step) 확장 지원

🤝 기여하기 (Contributing)
구조 엔지니어, 3D 웹 개발자, 오픈소스 애호가 등 누구의 기여든 환영합니다! 버그 리포트, 기능 제안, Pull Request 모두 자유롭게 남겨주세요. 자세한 내용은 CONTRIBUTING.md를 참고해 주세요.

📄 라이선스 (License)
이 프로젝트는 MIT License에 따라 배포됩니다.
