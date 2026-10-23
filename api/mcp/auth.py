"""MCP 请求侧原语：来源 IP、渲染资源闸门、Bearer 提取与 OAuth 质询。

_actor_from_headers/_require_tool_actor/_optional_tool_actor 留在
api/mcp_server.py —— 它们消费 async_session 且是测试的 patch 面。
"""

import logging
from typing import Any

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, TextContent

from ..core import rate_limit
from ..core.config import settings
from ..core.rate_limit import RateLimitError
from ..core.security import Actor
from .errors import _rate_error_message, _render_busy
from .limits import (MCP_RENDER_ACTOR_INFLIGHT, MCP_RENDER_BUCKET,
                     MCP_RENDER_GLOBAL_INFLIGHT, MCP_RENDER_RATE_LIMIT)

logger = logging.getLogger(__name__)

def _client_ip(headers: Any) -> str | None:
    """匿名限流分桶键: 读 nginx 覆盖写入的 x-real-ip; 缺省 None,
    由调用方决定是否落桶(x-forwarded-for 首段可伪造, 不使用)。"""
    return rate_limit.client_ip(headers)


async def _render_enter(actor: Actor | None, headers: Any = None) -> list[str]:
    """进入渲染闸门, 返回已持有租约的身份列表(交给 _render_exit 释放)。"""
    held: list[str] = []
    try:
        ip = _client_ip(headers)
        if actor is not None:
            identity = f"actor:{actor.id}"
        elif ip:
            identity = f"anon:{ip}"
        else:
            # 拿不到来源 IP 时不落全站共用桶 —— 限流按来源分桶, 缺头记警。
            identity = None
            logger.warning(
                "MCP render without client IP (no x-real-ip): "
                "per-IP anonymous limit skipped")
        if identity is not None:
            await rate_limit.enforce(MCP_RENDER_BUCKET, identity, MCP_RENDER_RATE_LIMIT, 60)
        if actor is not None:
            if await rate_limit.acquire_lease(MCP_RENDER_BUCKET, identity, MCP_RENDER_ACTOR_INFLIGHT):
                held.append(identity)
            else:
                raise _render_busy()
        if await rate_limit.acquire_lease(MCP_RENDER_BUCKET, "global", MCP_RENDER_GLOBAL_INFLIGHT):
            held.append("global")
        else:
            raise _render_busy()
        return held
    except ToolError:
        await rate_limit.release_leases(held, MCP_RENDER_BUCKET)
        raise
    except RateLimitError as exc:
        # enforce/lease 侧 fail-closed 的 LimiterUnavailable 与 RateLimited
        # 统一转成 MCP ToolError(.R: core 已 neutral, 此处捕语义异常)。
        await rate_limit.release_leases(held, MCP_RENDER_BUCKET)
        raise ToolError(_rate_error_message(exc)) from exc


async def _render_exit(held: list[str]) -> None:
    await rate_limit.release_leases(held, MCP_RENDER_BUCKET)

def _bearer(headers: Any) -> str | None:
    """Extract Authorization header from MCP request context headers."""
    if not headers:
        return None
    value = headers.get("authorization") or headers.get("Authorization")
    if value and value.lower().startswith("bearer "):
        return value
    return None


def _quote_auth_parameter(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _oauth_challenge(
    scope: str,
    *,
    error: str,
    description: str,
) -> CallToolResult:
    resource_metadata = (
        f"{settings.public_base_url.rstrip('/')}"
        "/.well-known/oauth-protected-resource/mcp"
    )
    challenge = (
        'Bearer '
        f'resource_metadata="{_quote_auth_parameter(resource_metadata)}", '
        f'scope="{_quote_auth_parameter(scope)}", '
        f'error="{_quote_auth_parameter(error)}", '
        f'error_description="{_quote_auth_parameter(description)}"'
    )
    return CallToolResult(
        content=[TextContent(type="text", text=description)],
        is_error=True,
        _meta={"mcp/www_authenticate": [challenge]},
    )
