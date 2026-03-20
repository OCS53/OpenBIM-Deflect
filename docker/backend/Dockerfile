# FastAPI + 스파이크 파이프라인(IfcOpenShell, Gmsh, CalculiX) 동일 베이스
FROM ubuntu:22.04

LABEL org.opencontainers.image.title="OpenBIM-Deflect API"
LABEL org.opencontainers.image.description="FastAPI backend running IFC spike pipeline"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPO_ROOT=/work \
    JOB_DATA_DIR=/work/backend/data/jobs

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

WORKDIR /work

COPY backend/requirements.txt /work/backend/requirements.txt
RUN python3 -m pip install --no-cache-dir -r /work/backend/requirements.txt

COPY backend /work/backend
COPY scripts /work/scripts
COPY sample /work/sample

WORKDIR /work/backend

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
