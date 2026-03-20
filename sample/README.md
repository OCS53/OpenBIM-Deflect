# 샘플 IFC (MVP 테스트용)

**보·기둥** 단일 부재와, **10층 모듈형 건물** 샘플을 포함합니다. 파이프라인(로드 → 메쉬 → 해석) 및 뷰어 검증용입니다.

| 파일 | 설명 |
|------|------|
| `simple_beam.ifc` | 직사각형 단면 200×300 mm, 경간 4000 mm (대략 +X 방향) |
| `simple_column.ifc` | 직사각형 단면 300×300 mm, 높이 3000 mm (+Z 방향) |
| `ten_story_4columns_slab.ifc` | 10 `IfcBuildingStorey`, 층마다 모서리 기둥 4개(400×400 mm) + 바닥 슬래브 1장(200 mm), 평면 8 m × 6 m, 층고 3 m |

## 재생성 방법

IfcOpenShell이 필요합니다. 저장소 루트에서:

```bash
python3 -m venv .venv
.venv/bin/pip install -r sample/requirements.txt
.venv/bin/python sample/generate_fixtures.py
```

`generate_fixtures.py`가 위 세 `.ifc` 파일을 덮어씁니다.
