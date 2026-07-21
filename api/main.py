"""FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .admin import router as admin_router
from .config import settings
from .database import engine
from .enrichment import router as enrichment_router
from .mol import router as molecule_router
from .rate_limit import consume, is_loopback_host, request_identity
from .reactions import router as reaction_write_router
from .routes import router as chemistry_router
from .social import router as social_router
from .users import auth_router, router as users_router
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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
)
app.include_router(chemistry_router, prefix="/api")
app.include_router(molecule_router, prefix="/api")
app.include_router(enrichment_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(reaction_write_router, prefix="/api")
app.include_router(social_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(workapi_router, include_in_schema=False)


@app.middleware("http")
async def public_api_rate_limit(request, call_next):
    if not request.url.path.startswith("/api") or request.url.path in {
        "/api/health", "/api/openapi.json", "/api/docs", "/api/redoc",
    } or is_loopback_host(request.client.host if request.client else None):
        return await call_next(request)
    is_render = request.url.path == "/api/mol/svg" or (
        request.url.path.startswith("/api/reactions/") and request.url.path.endswith("/svg")
    )
    bucket = "api-render" if is_render else "api"
    limit = settings.api_render_limit_per_minute if is_render else settings.api_query_limit_per_minute
    try:
        remaining, reset, allowed = await consume(
            bucket, request_identity(request), limit, 60
        )
    except Exception:
        return await call_next(request)
    if not allowed:
        return JSONResponse(
            {"detail": "请求过于频繁，请稍后重试"}, status_code=429,
            headers={"Retry-After": str(max(reset - int(__import__('time').time()), 1))},
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    response.headers["X-RateLimit-Reset"] = str(reset)
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.api_version}
