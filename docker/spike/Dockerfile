# 기술 스파이크용: IfcOpenShell(Python) + Gmsh(CLI·python3-gmsh) + CalculiX(ccx) 단일 이미지
# Ubuntu 22.04 LTS — jammy universe의 calculix-ccx, gmsh 사용

FROM ubuntu:22.04

LABEL org.opencontainers.image.title="OpenBIM-Deflect pipeline-spike"
LABEL org.opencontainers.image.description="Python + IfcOpenShell + Gmsh + CalculiX for offline pipeline experiments"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        python3 \
        python3-pip \
        python3-gmsh \
        gmsh \
        calculix-ccx \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir "ifcopenshell>=0.7.0,<0.9"

# 빌드 시점에 바이너리·임포트 확인
RUN set -eux; \
    command -v ccx; \
    command -v gmsh; \
    ccx -v 2>&1 | head -n 1; \
    gmsh --version | head -n 1; \
    python3 -c "import ifcopenshell, gmsh; print('ifcopenshell', ifcopenshell.version); print('gmsh module ok')"

# 마운트 없이 이미지만 쓸 때: 스파이크가 `app.analysis` 를 임포트하므로 backend 앱 + pydantic 필요
COPY backend/app /work/backend/app
COPY scripts /work/scripts
RUN python3 -m pip install --no-cache-dir "pydantic>=2,<3"

WORKDIR /work

# 기본: 저장소를 마운트한 뒤 toolcheck 실행 (compose에서 덮어쓸 수 있음)
CMD ["python3", "scripts/spike/toolcheck.py"]
