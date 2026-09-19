"""FastAPI application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .admin import router as admin_router
from .agent import router as agent_router
from .core.config import settings
from .core.database import engine
from .mcp_server import mcp_session_lifespan, mount_mcp
from .mol import router as molecule_router
from .reactions import router as reaction_write_router
from .routes import router as chemistry_router
from .skills import router as skills_router
from .social import router as social_router
from .stoichiometry import router as stoichiometry_router
from .users import auth_router, router as users_router
from .workapi import router as workapi_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_session_lifespan():
        yield
    await engine.dispose()


app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    lifespan=lifespan,
    # MCP 发现机制是 /api/agent-guide 自描述文档; OpenAPI/文档不对公网暴露(B2 通道规范)
    docs_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
)
app.include_router(chemistry_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(molecule_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(reaction_write_router, prefix="/api")
app.include_router(social_router, prefix="/api")
app.include_router(stoichiometry_router, prefix="/api")
app.include_router(skills_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(workapi_router, include_in_schema=False)

# 0904: health 必须注册在 mount_mcp 之前 — MCP 子应用挂根会吞掉其后
# 所有路由(0831 151307d 回归, 0903 体检发现 /api/health 404)
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.api_version}

# MCP 面(M1): /mcp — Agent 连接器入口, stateless streamable-http.
mount_mcp(app)


# B2 通道规范: 公网入口统一为 Next BFF, FastAPI 只接受 loopback 与 MCP 透传流量.
# 原 per-IP 公共限流中间件随直连面一同消亡(全流量 loopback 必跳过=死代码);
# 按身份的 enforce(rate_limit.py)在各端点继续生效.
