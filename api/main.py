"""FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .community import router as community_router
from .config import settings
from .database import engine
from .enrichment import router as enrichment_router
from .mol import router as molecule_router
from .routes import router as chemistry_router
from .workapi import router as workapi_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(chemistry_router, prefix="/api")
app.include_router(molecule_router, prefix="/api")
app.include_router(community_router, prefix="/api")
app.include_router(enrichment_router, prefix="/api")
app.include_router(workapi_router, include_in_schema=False)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.api_version}
