import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.analyze import router as analyze_router
from app.api.routes.jobs import router as jobs_router

app = FastAPI(
    title="OpenBIM-Deflect API",
    version="0.1.0",
    description="IFC 업로드 후 스파이크 파이프라인(IFC→Gmsh→CalculiX) 실행",
)

_cors = os.environ.get("CORS_ORIGINS", "*").strip()
_origins = ["*"] if _cors == "*" else [x.strip() for x in _cors.split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
