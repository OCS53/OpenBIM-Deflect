# 기술 스파이크 (IfcOpenShell → Gmsh → CalculiX)

UI 없이 **한 Docker 이미지**에서 Python·IfcOpenShell·Gmsh·CalculiX(`ccx`)를 같이 쓰는 용도입니다.  
[`docs/MVP-v1.0-SPEC.md`](../../docs/MVP-v1.0-SPEC.md) §6.5와 맞춥니다.

## 요구 사항

- Docker 및 Docker Compose v2 (`docker compose`)

## 빌드 및 점검

저장소 루트에서:

```bash
docker compose build pipeline-spike
docker compose run --rm pipeline-spike
```

기본 `CMD`는 [`toolcheck.py`](toolcheck.py)로, 다음을 순서대로 확인합니다.

1. `ccx`, `gmsh` CLI 존재 및 버전 출력  
2. `ifcopenshell`로 `sample/simple_beam.ifc` 로드  
3. Gmsh Python API로 단위 큐브 3D 메쉬를 `/tmp/openbim_spike_box.msh`에 기록  
4. [`fixtures/minimal_cube/cube.inp`](fixtures/minimal_cube/cube.inp)로 CalculiX 정적 해석 1회 실행  

## 대화형 셸

```bash
docker compose run --rm pipeline-spike bash
# 컨테이너 안에서
python3 scripts/spike/toolcheck.py
```

## IFC → STL → Gmsh → CalculiX `.inp` 스파이크 스크립트

[`pipeline_ifc_gmsh_ccx.py`](pipeline_ifc_gmsh_ccx.py)는 **한 프로세스**에서 다음을 수행합니다.

1. IFC에서 첫 구조 부재(Beam/Column/…)를 고름  
2. IfcOpenShell **geom 삼각망** → ASCII **STL** (`intermediate_from_ifc.stl`)  
3. Gmsh에서 STL **createGeometry** → 체적 **3D 테트** → `volume_from_gmsh.msh` (삼각망이 닫힌 체로 분류되지 않으면 **축정렬 바운딩 박스 OCC** 로 폴백)  
4. 선형 사면체만 **C3D4**로 풀어 `model_from_pipeline.inp` 작성 (최소 Z 노드 고정·최대 Z 노드에 `-Z` 하중 휴리스틱)  
5. 선택: `--run-ccx` 시 `ccx` 1회 후 `model_from_pipeline.frd`를 출력 폴더에 복사 (CalculiX 입력에 `*NODE FILE` / `*EL FILE` 이 포함되어 FRD에 DISP·STRESS 블록이 생김)  

```bash
docker compose run --rm pipeline-spike \
  python3 scripts/spike/pipeline_ifc_gmsh_ccx.py --ifc sample/simple_beam.ifc --run-ccx
```

- **`--geometry-strategy`:** `auto`(기본), `stl_classify`, `stl_raw`, `occ_bbox` — Gmsh에서 STL 치유(`classifySurfaces`) 단계를 쌓은 뒤 `auto`는 bbox 폴백.
- 실행 후 **`pipeline_report.json`** 에 실제 사용된 `gmsh_volume_strategy` 가 기록됩니다.

산출물 기본 디렉터리: `scripts/spike/_output/` (gitignore).  
`sample/simple_beam.ifc` 좌표는 **mm** 스케일이므로 기본 `--young`은 **210000 (MPa)** 로 두었습니다. m 기반 모델이면 `--young 2.1e11` 등으로 맞추세요.

### 뼈대 한계 (의도적)

- 중간 형상이 **STL 삼각망**뿐 — 정밀 해석에는 **STEP/BREP** 등으로 교체 여지 있음  
- IfcOpenShell STL은 Gmsh `createGeometry`에 자주 실패하므로, 스크립트는 **OCC 바운딩 박스**로 폴백합니다 (배선 검증용).  
- CalculiX 입력의 `*NSET` 등은 **한 줄 최대 16개 항목** 제한을 맞추도록 나뉩니다.  
- 경계·하중은 **자동 휴리스틱** — 실제 지지/하중과 다를 수 있음  
- Gmsh **3차원 선형 사면체(C3D4)** 만 지원 — C3D10 등은 TODO  

## 다음 단계 (파이프라인 본체)

- IFC에서 추출한 BREP/STEP 등 **중간 형상** 고도화 및 재질·단면 메타데이터 반영  
- CalculiX 입력의 **경계 조건·하중**을 UI/IFC와 일치시키기  

이미지 정의: [`docker/spike/Dockerfile`](../../docker/spike/Dockerfile)
