"""MCP server: the curated agent-facing capability surface.

认知模型:
- /mcp = curated MCP tool surface(人工挑选、显式命名的工具面), 是 AI /
  Agent 的唯一接入面; REST(/api/*) 只服务网站, 不接受 AI Key。
- MCP 工具**不从** OpenAPI 自动生成, 与 REST 只共享同一批业务服务函数与
  同一套授权规则(resolve_actor / scopes)。
- HTTP 能力允许比 MCP 多(例: 技能 zip 二进制下载 /skills/{id}/archive 只有
  HTTP 面, 不映射为 MCP 工具)。工具数量不作对齐目标。

设计锚点(全部基于已核实事实):
- mcp SDK 2.1.1: MCPServer + streamable_http_app() -> Starlette, mount 进 FastAPI.
- pm2 --workers 2: 必须 stateless_http=True(有状态 session 绑单 worker 内存,
  nginx 轮询跨 worker 必 404). stateless = 每请求独立 context.
- 认证: 不用 SDK token_verifier(它是传输层全量强制门, 匿名 initialize 都过不去,
  与 mixed anonymous/OAuth 工具冲突). 每工具从 ctx.headers 读 Authorization:
  既保留既有 HGS AI Key, 又支持 MCP OAuth access token; OAuth 只在 MCP adapter
  解析为 Actor, 不自动扩大 REST Bearer 权限。
- DNS rebinding 防护: host 默认 127.0.0.1 会触发 localhost-only Host 校验,
  挂在公网域名后必 403 — 传 transport_security 显式关闭(nginx 层已有真实边界).
- thin wrapper 直调服务层函数(与 REST handler 共享同一函数), 不自调 HTTP.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI
from pydantic import Field

from .core.rate_limit import RateLimitError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from sqlalchemy import text

from .core import rate_limit
from .core.config import settings
from .core.database import async_session

logger = logging.getLogger(__name__)

# 实现层四件套(限值/错误映射/请求侧原语/输出投影)按名绑定到本模块命名空间 ——
# 工具体与测试的 patch/属性面仍朝向 api.mcp_server。
from .mcp.errors import (
    _english_validation_message, _rate_error_message, _reaction_error_message, _search_error_message,
    _skill_error_message, _stoichiometry_error_message, _validation_error_message,
)
from .mcp.auth import (
    _bearer, _client_ip, _oauth_challenge, _render_enter,
    _render_exit,
)
from .mcp.limits import (
    IDEMPOTENCY_KEY_MAX_LENGTH, ID_MAX, LIST_PAGE_MAX, MCP_RENDER_BUCKET,
    MCP_RENDER_GLOBAL_INFLIGHT, MCP_RENDER_RATE_LIMIT, MY_REACTIONS_PAGE_SIZE_DEFAULT, MY_REACTIONS_PAGE_SIZE_MAX,
    QUERY_MAX_LENGTH, RENDER_SIZE_MAX, RENDER_SIZE_MIN, SEARCH_PAGE_MAX,
    SEARCH_PAGE_SIZE_DEFAULT, SEARCH_PAGE_SIZE_MAX, SKILL_CATEGORY_MAX_LENGTH, SKILL_QUERY_MAX_LENGTH,
    SMILES_MAX_LENGTH, THRESHOLD_MAX, THRESHOLD_MIN,
)
from .mcp.projections import (
    _clean_doc, _public_chemical, _public_reaction, _public_search,
    _public_skill,
)

from .schemas.reactions import ReactionBody
from .core.security import Actor, resolve_actor
from .schemas.stoichiometry import ScaleInput


# Tool annotations describe business/domain side effects. Operational state such
# as rate-limit counters, cache entries, and in-flight leases is not considered
# a user-visible mutation; otherwise every protected read would become a write.
ANN_READ_CLOSED = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True,
    open_world_hint=False,
)
ANN_SEARCH_OPEN = ToolAnnotations(
    # exact misses may create HCID rows and/or enqueue external-source work.
    read_only_hint=False, destructive_hint=False, idempotent_hint=False,
    open_world_hint=True,
)
ANN_CHEMICAL_OPEN = ToolAnnotations(
    # enrich=full may enqueue PubChem/CB enrichment and commit queue state.
    read_only_hint=False, destructive_hint=False, idempotent_hint=False,
    open_world_hint=True,
)
ANN_CREATE_CLOSED = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True,
    open_world_hint=False,
)
ANN_CREATE_OPEN = ToolAnnotations(
    # reaction creation may create HCIDs and enqueue identity discovery.
    read_only_hint=False, destructive_hint=False, idempotent_hint=True,
    open_world_hint=True,
)

# OpenAI/MCP auth metadata. Existing HGS AI Keys remain accepted at runtime;
# securitySchemes describe the standardized connection path available to hosts.
SEC_NOAUTH = {"securitySchemes": [{"type": "noauth"}]}
SEC_OPTIONAL_READ = {
    "securitySchemes": [
        {"type": "noauth"},
        {"type": "oauth2", "scopes": ["read"]},
    ]
}
SEC_OAUTH_READ = {"securitySchemes": [{"type": "oauth2", "scopes": ["read"]}]}
SEC_OAUTH_REACTION_WRITE = {
    "securitySchemes": [{"type": "oauth2", "scopes": ["reaction:write"]}]
}
SEC_OAUTH_SKILL_WRITE = {
    "securitySchemes": [{"type": "oauth2", "scopes": ["skill:write"]}]
}






# ---------------------------------------------------------------------------
# MCP serverInfo.version(B6)
# ---------------------------------------------------------------------------

def _release_version() -> str:
    """MCP serverInfo.version = 仓库根 VERSION(产品发布版本)。

    版本号只有一个来源 —— settings.api_version 读同一文件
    (api/core/config.py 的 _version_from_repo), 两处不分版本轴。
    这里只读文件, 不硬编码第二份版本号。
    """
    version_file = Path(__file__).resolve().parents[1] / "VERSION"
    try:
        value = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:  # pragma: no cover - 文件缺失即发布产物不完整
        raise RuntimeError("仓库根 VERSION 文件缺失: MCP serverInfo.version 无权威来源") from exc
    if not value:
        raise RuntimeError("仓库根 VERSION 文件为空: MCP serverInfo.version 无权威来源")
    return value


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------



async def _actor_from_headers(headers: Any) -> Actor | None:
    """Resolve existing HGS AI Key or MCP OAuth token; None means anonymous."""
    auth = _bearer(headers)
    if not auth:
        return None
    token = auth[7:].strip()
    async with async_session() as session:
        if token.startswith("hgo_at_"):
            from .services.oauth import mcp_resource_url, resolve_access_token

            row = await resolve_access_token(
                session, token, expected_resource=mcp_resource_url())
            if row is None:
                return None
            return Actor(
                int(row["user_id"]),
                str(row["username"]),
                str(row["display_name"]),
                str(row["email"]),
                str(row["role"]),
                row["avatar_path"],
                "oauth",
                int(row["id"]),
                tuple(row["scopes"] or ()),
            )
        return await resolve_actor(
            session, authorization=auth, session_token=None)


async def _require_tool_actor(
    headers: Any,
    *,
    oauth_scope: str,
    agent_scope: str | None,
) -> tuple[Actor | None, CallToolResult | None]:
    """Authenticate one protected tool without turning /mcp into a global gate.

    Existing HGS AI Keys preserve their historical scope semantics. OAuth
    credentials enforce the scope advertised in tool securitySchemes and return
    the MCP challenge metadata ChatGPT needs to launch account linking.
    """
    auth = _bearer(headers)
    actor = await _actor_from_headers(headers)
    if actor is None:
        if auth and auth[7:].strip().startswith("hgs_"):
            raise ToolError(
                "Authentication required. Connect an HGS AI Key with "
                "Authorization: Bearer <AI Key>."
            )
        description = (
            "Authentication required. Connect your HGS account to continue."
            if not auth else
            "The supplied access token is invalid or expired. Reconnect your HGS account."
        )
        return None, _oauth_challenge(
            oauth_scope, error="invalid_token", description=description)

    if actor.auth_kind == "oauth":
        if oauth_scope not in actor.scopes:
            return None, _oauth_challenge(
                oauth_scope,
                error="insufficient_scope",
                description=f"The connection needs the {oauth_scope} scope.",
            )
        return actor, None

    if actor.auth_kind == "agent":
        if agent_scope is not None and agent_scope not in actor.scopes:
            raise ToolError(
                f"The credential is missing the required scope: {agent_scope}.")
        return actor, None

    raise ToolError("Unsupported authentication type.")


async def _optional_tool_actor(
    headers: Any,
    *,
    oauth_scope: str,
) -> tuple[Actor | None, CallToolResult | None]:
    """Optional identity for mixed public/private tools.

    Anonymous calls stay anonymous. Existing HGS AI Keys preserve their historic
    behavior. An OAuth credential, however, must be valid and carry the scope
    advertised by the tool before it may unlock user-private data.
    """
    auth = _bearer(headers)
    actor = await _actor_from_headers(headers)
    if actor is None:
        if auth and auth[7:].strip().startswith("hgo_at_"):
            return None, _oauth_challenge(
                oauth_scope,
                error="invalid_token",
                description=(
                    "The supplied access token is invalid or expired. "
                    "Reconnect your HGS account."
                ),
            )
        return None, None

    if actor.auth_kind == "oauth" and oauth_scope not in actor.scopes:
        return None, _oauth_challenge(
            oauth_scope,
            error="insufficient_scope",
            description=f"The connection needs the {oauth_scope} scope.",
        )
    return actor, None


async def _resolve_skill_slug(candidate: str, actor: Actor | None) -> int:
    """slug → skill id。真实约束只有 UNIQUE(owner_id, slug), slug 全库不唯一。

    - anonymous: 只在 visibility='public' 内解析。
    - authenticated: 候选集 = visibility='public' OR owner_id=actor.id。
    - 0 命中 → not found; 1 命中 → 返回; >1 命中 → ToolError(要求用 numeric skill_id)。
    禁止 ORDER BY 取首条、owner 优先、public 优先、hottest/newest; 错误信息不得
    泄露存在但不可访问的 private 技能。
    """
    if actor is None:
        sql = "SELECT id FROM community.skills WHERE slug=:slug AND visibility='public'"
        params: dict[str, Any] = {"slug": candidate}
    else:
        sql = ("SELECT id FROM community.skills WHERE slug=:slug "
               "AND (visibility='public' OR owner_id=:actor_id)")
        params = {"slug": candidate, "actor_id": actor.id}
    async with async_session() as session:
        rows = (await session.execute(text(sql), params)).scalars().all()
    if not rows:
        raise ToolError(f"Skill slug not found or not accessible: {candidate!r}.")
    if len(rows) > 1:
        raise ToolError(
            f"Multiple accessible skills use slug {candidate!r}; specify a numeric skill_id."
        )
    return int(rows[0])




def build_mcp_server() -> MCPServer:
    server = MCPServer(
        name="huagongshe-aichem",
        # title 是客户端 UI 里展示的服务名(不带协议后缀); name 是机器标识,
        # 已被接入方当作稳定 ID 引用, 不得变更。
        title="HGS AIchem",
        # serverInfo.version = 产品发布版本(仓库根 VERSION);
        # settings.api_version 读同一文件, 版本号单一来源。
        version=_release_version(),
        instructions=(
            "HGS provides chemical and reaction context, stoichiometry, reusable skills, "
            "and user-owned reaction records. Public tools may be used anonymously; "
            "structure search, private data, and write actions require authentication. "
            "Before creating a user-owned record, show the intended content to the user "
            "and obtain confirmation. New reactions should default to private. Never "
            "invent structures, identifiers, sources, conditions, or yields. When values "
            "for the same property differ, present them side by side. HCID is the HGS "
            "chemical identifier; HRID is the HGS reaction identifier."
        ),
    )

    # 包装 tool 注册 —— 描述统一 dedent+strip(docstring 原样带
    # 嵌套缩进与尾随空白进 tools/list), 其余参数透传。
    _register_tool = server.tool

    def _tool(**kwargs):
        def deco(fn):
            if fn.__doc__ and "description" not in kwargs:
                kwargs["description"] = _clean_doc(fn.__doc__)
            return _register_tool(**kwargs)(fn)
        return deco

    server.tool = _tool

    # ---------------- 查询与读取工具 ----------------

    @server.tool(name="search_chemistry_data", title="Search chemistry data", annotations=ANN_SEARCH_OPEN, meta=SEC_OPTIONAL_READ)
    async def search_chemistry_data(
        q: Annotated[str, Field(
            min_length=1, max_length=QUERY_MAX_LENGTH,
            description="Query string: chemical or reaction name, CAS number, "
                        "HCID, PubChem CID, InChIKey, DOI, SMILES, or reaction "
                        "SMILES.")],
        mode: Annotated[Literal["exact", "substructure", "similarity"], Field(
            description="Search mode. exact matches identifiers and names; "
                        "substructure and similarity take a SMILES query and "
                        "require authentication.")] = "exact",
        threshold: Annotated[float, Field(
            ge=THRESHOLD_MIN, le=THRESHOLD_MAX,
            description="Similarity cutoff, only used when mode=similarity.")] = 0.7,
        page: Annotated[int, Field(
            ge=1, le=SEARCH_PAGE_MAX, description="Result page number.")] = 1,
        page_size: Annotated[int, Field(
            ge=1, le=SEARCH_PAGE_SIZE_MAX,
            description="Results per page.")] = SEARCH_PAGE_SIZE_DEFAULT,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Search chemicals and reactions by name, CAS, HCID, PubChem CID, InChIKey,
        DOI, SMILES, substructure, or similarity.

        mode: exact (default), substructure, or similarity.
        threshold: similarity cutoff from 0.4 to 1.0 (default 0.7).
        total=None means a complete total was not computed for this search mode.
        lookup_pending=true means an unknown CAS number is being looked up; search
        again later.
        has_more is authoritative for pagination; do not infer it from total.
        capped=true can occur for substructure search when the 250-result product
        cap is reached. In that case the database-wide match count is unknown.
        """
        if mode not in ("exact", "substructure", "similarity"):
            raise ToolError("mode must be one of: exact, substructure, similarity.")
        q = (q or "").strip()
        if not q or len(q) > QUERY_MAX_LENGTH:
            raise ToolError("q is required and must not exceed 4000 characters.")
        page = min(max(page, 1), SEARCH_PAGE_MAX)
        page_size = min(max(page_size, 1), SEARCH_PAGE_SIZE_MAX)
        # threshold 3位小数契约(与 REST routes.py #6 同口径): 不round则
        # 0.70004 穿透到 REST 层吃 422, 错误信息对 MCP 客户端不可解。
        threshold = round(min(max(threshold, THRESHOLD_MIN), THRESHOLD_MAX), 3)
        # 结构检索登录墙与 REST 一致: mode!=exact 需 Bearer token, 匿名 ToolError.
        # exact 保持原样(匿名, 不透传 actor).
        actor = None
        if mode != "exact":
            actor, auth_result = await _require_tool_actor(
                ctx.headers if ctx else None,
                oauth_scope="read",
                agent_scope=None,
            )
            if auth_result is not None:
                return auth_result  # type: ignore[return-value]
            assert actor is not None
        # 直调 shared search orchestration(services/search.py
        # execute_search)—— cache/结构闸门/canonicalize/查询/结果组装唯一 owner。
        # adapter 只保留: 参数验证/clamp、auth、会话获取、错误映射。
        from .services.search import SearchError as _SearchError
        from .services.search import execute_search as _execute_search

        async with async_session() as _session:
            try:
                return _public_search(await _execute_search(
                    _session, q, mode, threshold=threshold, page=page,
                    page_size=page_size,
                    actor_id=actor.id if actor else None,
                    client_ip=_client_ip(ctx.headers if ctx else None),
                ))
            except _SearchError as exc:
                raise ToolError(_search_error_message(exc)) from exc
            except RateLimitError as exc:
                raise ToolError(_rate_error_message(exc)) from exc

    @server.tool(name="get_chemical", title="Get chemical", annotations=ANN_CHEMICAL_OPEN, meta=SEC_NOAUTH)
    async def get_chemical(
        chemical_id: Annotated[int, Field(
            ge=1, le=ID_MAX, description="HCID, the HGS chemical identifier.")],
        enrich: Annotated[Literal["core", "full"], Field(
            description="core returns identifiers, names, formula, masses and "
                        "structure; full adds semantic detail (properties, "
                        "safety, industry, suppliers).")] = "core",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Return one chemical by HCID.

        enrich=core returns identifiers, names, formula, masses and structure.
        enrich=full also returns the description, names and aliases, computed and
        experimental properties, safety and regulatory information, applications,
        related products, reagent prices and suppliers.
        """
        if enrich not in ("core", "full"):
            raise ToolError("enrich must be either core or full.")
        if not 1 <= chemical_id <= ID_MAX:
            raise ToolError("chemical_id is out of range.")
        # 直调 shared detail orchestration(services/chemicals)。
        # auth 行为冻结: 恒匿名(actor 不解析), priority=50 与基线一致。
        from .services.chemicals import (
            ChemicalNotFoundError as _ChemicalNotFoundError,
            get_chemical_detail as _get_chemical_detail,
            normalize_enrich as _normalize_enrich,
        )

        async with async_session() as session:
            try:
                return _public_chemical(await _get_chemical_detail(
                    session, chemical_id,
                    actor_id=None, priority=50,
                    enrich=_normalize_enrich(enrich),
                ))
            except _ChemicalNotFoundError as exc:
                raise ToolError("Chemical not found.") from exc

    @server.tool(name="get_reaction", title="Get reaction", annotations=ANN_READ_CLOSED, meta=SEC_OPTIONAL_READ)
    async def get_reaction(
        reaction_id: Annotated[int, Field(
            ge=1, le=ID_MAX,
            description="HRID, the HGS reaction identifier.")],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Return one reaction by HRID. With an authenticated credential, the owner may
        also read their own private reaction record."""
        from .services.reactions import load_reaction_detail

        actor, auth_result = await _optional_tool_actor(
            ctx.headers if ctx else None, oauth_scope="read")
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        if not 1 <= reaction_id <= ID_MAX:
            raise ToolError("reaction_id is out of range.")
        # 直调 transport-neutral service(None=不存在或不可见);
        # auth 行为冻结: 无/无效 credential → anonymous(viewer_id=0)。
        async with async_session() as session:
            data = await load_reaction_detail(
                session, reaction_id,
                viewer_id=actor.id if actor else 0,
                viewer_is_admin=bool(actor and actor.role == "admin"),
            )
            if data is None:
                raise ToolError("Reaction not found.")
            return _public_reaction(data)

    @server.tool(name="render_molecule_svg", title="Render molecule SVG", annotations=ANN_READ_CLOSED, meta=SEC_NOAUTH)
    async def render_molecule_svg(
        chemical_id: Annotated[int | None, Field(
            ge=1, le=ID_MAX,
            description="HCID to render. Provide either chemical_id or smiles.")] = None,
        smiles: Annotated[str | None, Field(
            max_length=SMILES_MAX_LENGTH,
            description="SMILES to render instead of a chemical_id.")] = None,
        width: Annotated[int, Field(
            ge=RENDER_SIZE_MIN, le=RENDER_SIZE_MAX,
            description="Output width in pixels (clamped to range).")] = 400,
        height: Annotated[int, Field(
            ge=RENDER_SIZE_MIN, le=RENDER_SIZE_MAX,
            description="Output height in pixels (clamped to range).")] = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """Render a 2D molecular structure as SVG text.

        Provide either chemical_id for an HGS chemical or smiles for a direct
        structure (maximum 512 characters). width and height are clamped to
        50-800 pixels.
        """
        from .services import rendering as render_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        width = min(max(width, RENDER_SIZE_MIN), RENDER_SIZE_MAX)
        height = min(max(height, RENDER_SIZE_MIN), RENDER_SIZE_MAX)
        target_smiles: str | None = None
        if chemical_id is not None:
            async with async_session() as session:
                target_smiles = await render_service.lookup_molecule_smiles(
                    session, chemical_id)
            if target_smiles is None:
                raise ToolError("Chemical not found or has no renderable structure.")
        elif smiles:
            target_smiles = smiles.strip()
            # 外部直传 SMILES 的 resource bound: 实测 ~4000 字符合法
            # SMILES 可让 RDKit render 占分钟级 CPU。512 只管用户直传;
            # chemical_id 路径的 SMILES 来自 DB(受写入校验), 不套用。
            # guard 必须在 RDKit 之前。
            if len(target_smiles) > SMILES_MAX_LENGTH:
                raise ToolError("SMILES must not exceed 512 characters.")
        else:
            raise ToolError("Provide exactly one structure source: chemical_id or smiles.")
        if not target_smiles:
            raise ToolError("No renderable structure is available.")
        import asyncio as _asyncio

        # 资源闸门在 RDKit to_thread 之前; 与 render_reaction_svg 共用同一池。
        held = await _render_enter(actor, ctx.headers if ctx else None)
        try:
            svg = await _asyncio.to_thread(render_service.smiles_to_svg, target_smiles, width, height)
        finally:
            await _render_exit(held)
        if svg is None:
            raise ToolError("The SMILES could not be rendered.")
        return svg

    @server.tool(name="render_reaction_svg", title="Render reaction SVG", annotations=ANN_READ_CLOSED, meta=SEC_OPTIONAL_READ)
    async def render_reaction_svg(
        reaction_id: Annotated[int, Field(
            ge=1, le=ID_MAX, description="HRID to render.")],
        width: Annotated[int, Field(
            ge=RENDER_SIZE_MIN, le=RENDER_SIZE_MAX,
            description="Output width in pixels (clamped to range).")] = 800,
        height: Annotated[int, Field(
            ge=RENDER_SIZE_MIN, le=RENDER_SIZE_MAX,
            description="Output height in pixels (clamped to range).")] = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """Render a reaction equation as SVG text.

        width and height are clamped to 50-800 pixels. The default output size is
        800×300.
        """
        from .services import rendering as render_service

        actor, auth_result = await _optional_tool_actor(
            ctx.headers if ctx else None, oauth_scope="read")
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        width = min(max(width, RENDER_SIZE_MIN), RENDER_SIZE_MAX)
        height = min(max(height, RENDER_SIZE_MIN), RENDER_SIZE_MAX)
        async with async_session() as session:
            source = await render_service.lookup_reaction_render_source(
                session, reaction_id,
                viewer_id=actor.id if actor else 0,
                is_admin=bool(actor and actor.role == "admin"))
        if source is None:
            raise ToolError("Reaction not found or has no renderable reaction expression.")
        import asyncio as _asyncio

        # 资源闸门在 RDKit to_thread 之前; 与 render_molecule_svg 共用同一池。
        held = await _render_enter(actor, ctx.headers if ctx else None)
        try:
            svg = await _asyncio.to_thread(
                render_service.reaction_to_svg, source.reaction_smiles,
                width, height)
        finally:
            await _render_exit(held)
        if svg is None:
            raise ToolError("The reaction SMILES could not be rendered.")
        return svg

    @server.tool(name="list_skills", title="List skills", annotations=ANN_READ_CLOSED, meta=SEC_OAUTH_READ)
    async def list_skills(
        scope: Annotated[Literal["public", "mine"], Field(
            description="public lists the public skill pool; "
                        "mine lists the caller's own skills. Both "
                        "require authentication.")] = "public",
        q: Annotated[str, Field(
            max_length=SKILL_QUERY_MAX_LENGTH,
            description="Optional case-insensitive title/slug filter.")] = "",
        category: Annotated[str, Field(
            max_length=SKILL_CATEGORY_MAX_LENGTH,
            description="Optional exact category filter.")] = "",
        page: Annotated[int, Field(
            ge=1, le=LIST_PAGE_MAX, description="Result page number.")] = 1,
        page_size: Annotated[int, Field(
            ge=1, le=SEARCH_PAGE_SIZE_MAX,
            description="Results per page.")] = SEARCH_PAGE_SIZE_DEFAULT,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """List reusable skills (login required). scope=public lists the public
        skill pool; scope=mine lists the caller's own skills."""
        from .services.skills import list_skills as _list_service

        # 技能浏览是登录能力(HTTP GET /skills 同墙): public 与 mine 都要
        # 求登录; AI Key 保留, OAuth 依 advertised read scope。
        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="read",
            agent_scope=None,
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        if scope not in ("public", "mine"):
            raise ToolError("scope must be either public or mine.")
        q = (q or "")[:120]
        category = (category or "")[:40]
        page = min(max(page, 1), LIST_PAGE_MAX)
        page_size = min(max(page_size, 1), SEARCH_PAGE_SIZE_MAX)
        # 直调 shared service(skill.query.list kernel)。
        async with async_session() as session:
            listed = await _list_service(
                session, scope=scope, owner_id=actor.id if scope == "mine" else None,
                q=q, category=category, page=page, page_size=page_size,
            )
            return {**listed, "items": [_public_skill(i) for i in listed.get("items") or []]}

    @server.tool(name="get_skill", title="Get skill", annotations=ANN_READ_CLOSED, meta=SEC_OAUTH_READ)
    async def get_skill(
        skill_id: Annotated[int | str, Field(
            description="Numeric skill ID or slug, e.g. "
                        "huagongshe-reaction-publisher.")],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Return a skill manifest, file list, and full SKILL.md text
        (login required).

        skill_id accepts either a numeric ID or a slug such as
        huagongshe-reaction-publisher. Binary file contents are not returned.
        """
        from .services.skills import SkillNotAccessibleError
        from .services.skills import get_skill_detail as _detail_service

        # 技能浏览是登录能力(HTTP GET /skills/{id} 同墙)。
        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="read",
            agent_scope=None,
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        if isinstance(skill_id, str):
            candidate = skill_id.strip()
            if candidate.isdigit():
                resolved_id = int(candidate)
            else:
                resolved_id = await _resolve_skill_slug(candidate, actor)
        else:
            resolved_id = skill_id
        if not 1 <= resolved_id <= ID_MAX:
            raise ToolError("skill_id is out of range.")
        # 直调 shared detail service(slug 解析留本 adapter);
        # missing/private-unreadable → 同一 ToolError 原文。
        async with async_session() as session:
            try:
                return _public_skill(await _detail_service(
                    session, resolved_id,
                    actor_id=actor.id if actor else None))
            except SkillNotAccessibleError as exc:
                raise ToolError(_skill_error_message(exc)) from exc

    @server.tool(name="calculate_stoichiometry", title="Calculate stoichiometry", annotations=ANN_READ_CLOSED, meta=SEC_NOAUTH)
    async def calculate_stoichiometry(
        components: Annotated[list[dict[str, Any]], Field(
            description="Reaction components. Each entry uses role "
                        "(REACTANT/REAGENT/CATALYST/SOLVENT/PRODUCT), name, "
                        "amount fields, and optional molecular weight; see the "
                        "tool description for the full shape.")],
        basis: Annotated[dict[str, Any], Field(
            description="Basis for scaling: which component and which amount "
                        "field the new total applies to.")],
        concentration_mol_per_l: Annotated[float | None, Field(
            gt=0,
            description="Optional solution concentration (mol/L) used when "
                        "the basis is a volume.")] = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Scale a reaction formulation from one basis amount.

        components entries use role (REACTANT/REAGENT/CATALYST/SOLVENT/PRODUCT),
        smiles, eq, and optional label. basis contains index, amount_value, and
        amount_unit (g, mg, mol, or mmol). eq is required for non-solvent
        components. Maximum 30 components. Optionally provide
        concentration_mol_per_l for solvent volume calculation.
        """
        from .core import rate_limit as _rate_limit
        from .core.rate_limit import RateLimitError as _RateLimitError
        from .core.config import settings as _settings
        from .services import stoichiometry as stoich_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        try:
            body = ScaleInput(
                components=components, basis=basis,
                concentration_mol_per_l=concentration_mol_per_l,
            )
        except Exception as exc:
            raise ToolError(_validation_error_message("Invalid stoichiometry fields", exc)) from exc
        # 限流桶与 REST 同构: 登录=u{id} 桶; 匿名按来源 IP 分桶, 拿不到
        # 来源 IP 时不设限流并记警(不落全站共用桶)。
        _ip = _client_ip(ctx.headers if ctx else None)
        if actor:
            _identity = f"u{actor.id}"
        elif _ip:
            _identity = f"ip:{_ip}"
        else:
            _identity = None
            logger.warning(
                "stoichiometry without client IP (no x-real-ip): "
                "anonymous rate limit skipped")
        # 限流(RateLimited/LimiterUnavailable)与业务校验(ValueError)都在
        # MCP 边界转成 ToolError —— 客户端可读 detail 原文。
        try:
            if _identity is not None:
                await _rate_limit.enforce("stoich", _identity,
                                          _settings.api_stoich_limit_per_minute, 60)
            return await stoich_service.compute(body)
        except ValueError as exc:
            raise ToolError(_stoichiometry_error_message(exc)) from exc
        except _RateLimitError as exc:
            raise ToolError(_rate_error_message(exc)) from exc

    # ---------------- 写工具(需要 AI Key) ----------------

    @server.tool(name="list_my_reactions", title="List my reactions", annotations=ANN_READ_CLOSED, meta=SEC_OAUTH_READ)
    async def list_my_reactions(
        visibility: Annotated[Literal["all", "public", "private"], Field(
            description="Filter the caller's own reactions by visibility.")] = "all",
        page: Annotated[int, Field(
            ge=1, le=LIST_PAGE_MAX, description="Result page number.")] = 1,
        page_size: Annotated[int, Field(
            ge=1, le=MY_REACTIONS_PAGE_SIZE_MAX,
            description="Results per page.")] = MY_REACTIONS_PAGE_SIZE_DEFAULT,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """List reaction records owned by the authenticated HGS user."""
        from .services.reactions import list_my_reactions as _list_service

        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="read",
            agent_scope=None,
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        if visibility not in ("all", "public", "private"):
            raise ToolError("visibility must be one of: all, public, private.")
        page = min(max(page, 1), LIST_PAGE_MAX)
        page_size = min(max(page_size, 1), MY_REACTIONS_PAGE_SIZE_MAX)
        # 直调 shared service(clamp 保持, 不改 ToolError/拒绝).
        async with async_session() as session:
            listed = await _list_service(
                session, actor_id=actor.id, visibility=visibility,
                page=page, page_size=page_size,
            )
            return {**listed, "items": [
                {k: v for k, v in dict(i).items() if k != "moderation_status"}
                for i in listed.get("items") or []]}

    @server.tool(name="validate_reaction", title="Validate reaction draft", annotations=ANN_READ_CLOSED, meta=SEC_OAUTH_REACTION_WRITE)
    async def validate_reaction(
        reaction: Annotated[dict[str, Any], Field(
            description="Reaction draft to validate. Same field model as "
                        "create_reaction; nothing is saved.")],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Validate and normalize a reaction draft without saving it.

        Requires reaction:write permission.
        """
        from .core.rate_limit import RateLimitError as _RateLimitError
        from .services.reactions import ReactionValidationError
        from .services.reactions import validate_reaction_draft

        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="reaction:write",
            agent_scope="reaction:write",
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        try:
            body = ReactionBody(**reaction)
        except Exception as exc:
            raise ToolError(_validation_error_message("Invalid reaction draft fields", exc)) from exc
        # 直调 shared validation service(A005 validate 关闭);
        # neutral validation/rate error → ToolError(detail)。
        try:
            return await validate_reaction_draft(
                actor_id=actor.id, body=body)
        except ReactionValidationError as exc:
            raise ToolError(_reaction_error_message(exc)) from exc
        except _RateLimitError as exc:
            raise ToolError(_rate_error_message(exc)) from exc

    @server.tool(name="validate_skill", title="Validate skill package", annotations=ANN_READ_CLOSED, meta=SEC_OAUTH_SKILL_WRITE)
    async def validate_skill(
        zip_base64: Annotated[str, Field(
            min_length=1,
            description="Base64-encoded skill ZIP archive (same package "
                        "format as create_skill). Nothing is saved.")],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Validate a skill ZIP without saving it.

        Checks archive structure, quotas, frontmatter, script syntax, and risky
        call warnings. zip_base64 is the base64-encoded ZIP; the decoded archive
        is limited by the server's skill ZIP size policy.
        """
        import asyncio as _asyncio
        import base64 as _base64
        import binascii

        from .core.config import settings as _settings
        from .services.skills import SkillArchiveValidationError
        from .services.skills import extract_skill_zip as _extract_skill_zip

        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="skill:write",
            agent_scope="skill:write",
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        try:
            raw = _base64.b64decode(zip_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("zip_base64 is not valid base64.") from exc
        if len(raw) > _settings.skill_zip_max_bytes:
            raise ToolError(f"The archive exceeds the {_settings.skill_zip_max_bytes // (1024 * 1024)} MB limit.")
        try:
            manifest = await _asyncio.to_thread(_extract_skill_zip, raw)
            return {
                "ok": True,
                "slug": manifest["slug"], "title": manifest["title"],
                "description": manifest["description"], "license": manifest["license"],
                "has_scripts": manifest["has_scripts"],
                "file_count": manifest["file_count"], "size_bytes": manifest["size_bytes"],
                "warnings": manifest["warnings"],
                "files": [{"path": p, "size_bytes": len(d)} for p, d in manifest["files"]],
            }
        except SkillArchiveValidationError as exc:
            raise ToolError(_skill_error_message(exc)) from exc

    @server.tool(name="create_skill", title="Create skill", annotations=ANN_CREATE_CLOSED, meta=SEC_OAUTH_SKILL_WRITE)
    async def create_skill(
        zip_base64: Annotated[str, Field(
            min_length=1,
            description="Base64-encoded skill ZIP archive.")],
        category: Annotated[str | None, Field(
            max_length=SKILL_CATEGORY_MAX_LENGTH,
            description="Optional category slug from the public category "
                        "dictionary.")] = None,
        idempotency_key: Annotated[str, Field(
            max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
            description="Client-generated retry key; the same key never "
                        "creates a duplicate skill.")] = "",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Create a private skill from a user-confirmed ZIP package.

        Requires skill:write permission. Personal skills are always private.
        Reuse the same idempotency_key only when retrying the same create action.
        """
        import base64 as _base64
        import binascii

        from .core.rate_limit import RateLimitError as _RateLimitError
        from .services.skills import (MissingSkillIdempotencyKeyError,
                                      SkillArchiveValidationError,
                                      SkillCategoryError,
                                      SkillIdempotencyKeyTooLongError,
                                      SkillNotAccessibleError,
                                      SkillSlugConflictError)
        from .services.skills import create_skill as _create_skill_service

        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="skill:write",
            agent_scope="skill:write",
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        # 冻结 ordering: base64 decode 在 service/rate 之前
        # (非法 base64 不消耗 quota, service 零调用)。
        try:
            raw = _base64.b64decode(zip_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("zip_base64 is not valid base64.") from exc

        async def _archive_loader(limit: int) -> bytes:
            # 原 read(limit) slicing 语义逐字保持。
            return raw[:limit]

        try:
            # 直调 shared create service(handler-call A005 关闭);
            # neutral errors → ToolError(detail)。
            async with async_session() as session:
                return await _create_skill_service(
                    session, actor_id=actor.id, auth_kind=actor.auth_kind,
                    category=(category or None),
                    idempotency_key=(idempotency_key or None),
                    archive_loader=_archive_loader)
        except _RateLimitError as exc:
            raise ToolError(_rate_error_message(exc)) from exc
        except (SkillArchiveValidationError, SkillCategoryError,
                SkillSlugConflictError, MissingSkillIdempotencyKeyError,
                SkillIdempotencyKeyTooLongError, SkillNotAccessibleError) as exc:
            raise ToolError(_skill_error_message(exc)) from exc

    @server.tool(name="create_reaction", title="Create reaction", annotations=ANN_CREATE_OPEN, meta=SEC_OAUTH_REACTION_WRITE)
    async def create_reaction(
        reaction: Annotated[dict[str, Any], Field(
            description="User-confirmed reaction draft. Validate it first "
                        "with validate_reaction; required fields and "
                        "constraints are listed by that tool.")],
        idempotency_key: Annotated[str, Field(
            min_length=1, max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
            description="Client-generated retry key; the same key never "
                        "creates a duplicate reaction.")],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Create a user-confirmed reaction record.

        Requires reaction:write permission and an idempotency_key. Validate the
        draft first and obtain user confirmation before creating it. New records
        should default to private. The result includes the HRID, page URL, and any
        newly created HCIDs.
        """
        from .core.rate_limit import RateLimitError as _RateLimitError
        from .services.reactions import (IdempotencyKeyTooLongError,
                                         MissingIdempotencyKeyError)
        from .services.reactions import ReactionValidationError
        from .services.reactions import UnresolvedIdentityError
        from .services.reactions import create_reaction as _create_service

        actor, auth_result = await _require_tool_actor(
            ctx.headers if ctx else None,
            oauth_scope="reaction:write",
            agent_scope="reaction:write",
        )
        if auth_result is not None:
            return auth_result  # type: ignore[return-value]
        assert actor is not None
        # 冻结差异: MCP 侧 idempotency_key 必填且 ≤200, 检查在
        # service/rate 之前(service 不被调, quota 不消耗)。
        if not idempotency_key or len(idempotency_key) > IDEMPOTENCY_KEY_MAX_LENGTH:
            raise ToolError("idempotency_key is required and must not exceed 200 characters.")
        try:
            body = ReactionBody(**reaction)
        except Exception as exc:
            raise ToolError(_validation_error_message("Invalid draft fields", exc)) from exc
        try:
            # 直调 shared create service(A005 create 关闭);
            # neutral validation/rate/idempotency error → ToolError(detail)。
            async with async_session() as session:
                return await _create_service(
                    session, actor_id=actor.id, auth_kind=actor.auth_kind,
                    body=body, idempotency_key=idempotency_key)
        except _RateLimitError as exc:
            raise ToolError(_rate_error_message(exc)) from exc
        except (ReactionValidationError,
                MissingIdempotencyKeyError, IdempotencyKeyTooLongError) as exc:
            raise ToolError(_reaction_error_message(exc)) from exc
        except UnresolvedIdentityError as exc:
            # CONFLICT/AMBIGUOUS → no rows created.
            raise ToolError(_reaction_error_message(exc)) from exc

    return server


# ---------------------------------------------------------------------------
# FastAPI 集成
# ---------------------------------------------------------------------------

_mcp_server: MCPServer | None = None


def mcp_request_body_limit(skill_zip_max_bytes: int) -> int:
    """Streamable HTTP 请求体上限: 技能包工具收 Base64(zip), 请求体 =
    ZIP 上限 × 4/3 加 JSON 封装余量 —— 唯一来源是 settings 的 ZIP 上限,
    SDK 默认 4 MiB 装不下, 会把合规技能包挡在工具校验之前。"""
    return skill_zip_max_bytes * 4 // 3 + 2 * 1024 * 1024


def mount_mcp(app: FastAPI) -> None:
    """Build the MCP server and mount its streamable-http app at /mcp."""
    global _mcp_server
    _mcp_server = build_mcp_server()
    starlette_app = _mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        # DNS rebinding 防护按 host=127.0.0.1 默认开启且只放行 localhost Host 头,
        # 经 nginx(公网域名) 反代必 403 — 本服务边界在 nginx, 此处显式关闭.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        max_request_body_size=mcp_request_body_limit(settings.skill_zip_max_bytes),
        host="0.0.0.0",
    )
    # 终局: 挂根 + 子路径 /mcp → MCP 端点 = /mcp(规范路径, 关键路由锁死)。
    # 说明页让位至 /mcp-guide(Next)。原 /api/mcp 与 /api/mcp/mcp 由 nginx 308 兜底,
    # 已接入客户端不断连。挂根不影响 REST: 子应用只响应 /mcp, 其余路径穿透回父 404。
    app.mount("/", starlette_app)


def mcp_session_lifespan():
    """Async context manager: run the MCP session manager inside the app lifespan.

    实测(starlette 1.3.1): mount 的子 app lifespan 不会随父 app 启动 —
    session_manager.run() 必须由父 lifespan 显式进入, 否则所有 MCP 请求挂起.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _run():
        assert _mcp_server is not None, "mount_mcp() 必须先于 lifespan 执行"
        async with _mcp_server.session_manager.run():
            yield

    return _run()
