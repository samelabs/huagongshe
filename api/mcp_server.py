"""MCP server: the curated agent-facing capability surface (M1).

认知模型(与 /api/agent-guide 的关系, 不得再表述为 1:1):
- /api/agent-guide = HTTP Agent contract(自描述连接契约)。
- /mcp = curated MCP tool surface(人工挑选、显式命名的工具面)。
- MCP 工具**不从** OpenAPI / agent-guide 自动生成, 二者只是共享同一批业务
  服务函数与同一套授权规则(resolve_actor / scopes)。
- HTTP 能力允许比 MCP 多(例: 技能 zip 二进制下载 /skills/{id}/archive 只有
  HTTP 面, 不映射为 MCP 工具)。工具数量不作对齐目标。

设计锚点(全部基于已核实事实):
- mcp SDK 2.1.1: MCPServer + streamable_http_app() -> Starlette, mount 进 FastAPI.
- pm2 --workers 2: 必须 stateless_http=True(有状态 session 绑单 worker 内存,
  nginx 轮询跨 worker 必 404). stateless = 每请求独立 context.
- 认证: 不用 SDK token_verifier(它是传输层全量强制门, 匿名 initialize 都过不去,
  与"匿名只读 + Token 写"分层冲突). 每工具从 ctx.headers 读 Authorization,
  走 resolve_actor(与 REST 同一张 user_api_tokens 表, 同一套 scopes).
- DNS rebinding 防护: host 默认 127.0.0.1 会触发 localhost-only Host 校验,
  挂在公网域名后必 403 — 传 transport_security 显式关闭(nginx 层已有真实边界).
- thin wrapper 直调服务层函数(与 REST handler 共享同一函数), 不自调 HTTP.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from .core.rate_limit import RateLimitError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from sqlalchemy import text

from .core import rate_limit
from .core.config import settings
from .core.database import async_session
from .schemas.reactions import ReactionBody
from .core.security import Actor, resolve_actor
from .schemas.stoichiometry import ScaleInput

# ---------------------------------------------------------------------------
# MCP 渲染资源闸门(B5)
# ---------------------------------------------------------------------------
# 两个 render tool 共用同一资源池: render_molecule_svg / render_reaction_svg。
# RDKit 渲染是 CPU-bound(外部直传 SMILES 可占分钟级), 复用与结构检索同一组
# 原语: enforce(fixed-window 限频) + acquire_lease/release_lease(in-flight 租约)。
# - 已认证 actor 120 次/分钟, 匿名按来源 IP 各 120 次/分钟(x-forwarded-for),
#   匿名全局兜底 600 次/分钟(防分布式刷)
# - 已认证 actor in-flight ≤ 2(匿名不额外持 actor 租约)
# - 全局 in-flight ≤ 4
# - Redis acquire 失败 fail-closed(503 → ToolError), 不放行
# - 闸门必须在 RDKit to_thread 之前, finally 必释放
MCP_RENDER_BUCKET = "mcp-render"
MCP_RENDER_RATE_LIMIT = 120
MCP_RENDER_ANON_GLOBAL_LIMIT = 600
MCP_RENDER_ACTOR_INFLIGHT = 2
MCP_RENDER_GLOBAL_INFLIGHT = 4

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


def _render_busy() -> ToolError:
    return ToolError("Rendering concurrency limit reached. Try again shortly.")


def _validation_error_message(prefix: str, exc: Exception) -> str:
    """Keep field-level Pydantic context while exposing an English MCP error."""
    errors = getattr(exc, "errors", None)
    if callable(errors):
        parts: list[str] = []
        for item in errors()[:4]:
            loc = ".".join(str(value) for value in item.get("loc", ()))
            msg = str(item.get("msg", "invalid value"))
            parts.append(f"{loc}: {msg}" if loc else msg)
        if parts:
            return f"{prefix}: " + "; ".join(parts)
    return prefix


def _detail_tail(detail: str, marker: str) -> str:
    if marker not in detail:
        return ""
    return detail.split(marker, 1)[1].strip()


def _rate_error_message(exc: Exception) -> str:
    """English MCP boundary for neutral rate/resource errors."""
    name = type(exc).__name__
    if name == "RateLimited":
        return "Too many requests. Try again shortly."
    if name == "LimiterUnavailable":
        return "Rate-limit service is temporarily unavailable. Try again shortly."
    if name == "ResourceBusy":
        return "Structure-search concurrency limit reached. Try again shortly."
    return "The request could not be admitted by the resource limiter."


def _search_error_message(exc: Exception) -> str:
    kind = getattr(exc, "kind", "")
    if kind == "invalid_structure":
        return "The SMILES structure could not be recognized."
    if kind == "query_too_short":
        return "Name queries require at least 3 characters, or at least 2 CJK characters."
    if kind == "substructure_too_small":
        return "The substructure query is too small; provide a more specific structure."
    if kind == "invalid_doi":
        return "The DOI is invalid."
    if kind == "backend_unavailable":
        return "Search timed out. Use a more specific name, identifier, or structure."
    return "The chemistry search could not be completed."


def _reaction_error_message(exc: Exception) -> str:
    kind = getattr(exc, "kind", "")
    detail = str(getattr(exc, "detail", "") or "")
    if kind == "invalid_structure":
        value = _detail_tail(detail, "无法解析参与物结构：")
        return (
            f"Could not parse reaction participant structure: {value}"
            if value else "Could not parse a reaction participant structure."
        )
    if kind == "duplicate_participant":
        return "Merge duplicate entries with the same compound and role, then set occurrence_count."
    if kind == "invalid_reaction":
        return "The reaction structure could not be parsed by RDKit."
    status = getattr(exc, "status", "")
    if status == "CONFLICT":
        return "Chemical identity conflict prevents automatic reaction creation."
    if status == "AMBIGUOUS":
        return "Chemical identity is ambiguous; multiple candidates require manual resolution."
    name = type(exc).__name__
    if name == "MissingIdempotencyKeyError":
        return "idempotency_key is required for authenticated reaction creation."
    if name == "IdempotencyKeyTooLongError":
        return "idempotency_key must not exceed 200 characters."
    return "The reaction request could not be completed."


def _stoichiometry_error_message(exc: Exception) -> str:
    detail = str(exc)
    if detail.startswith("基准 index ") and detail.endswith(" 超出组分范围"):
        value = detail[len("基准 index "):-len(" 超出组分范围")]
        return f"Basis index {value} is outside the component range."
    if detail.startswith("组分 ") and "）缺少 eq（仅溶剂可留空）" in detail:
        middle = detail[len("组分 "):].split("）缺少 eq", 1)[0]
        if "（" in middle:
            index, role = middle.split("（", 1)
            return f"Component {index} ({role}) is missing eq; only solvent rows may omit eq."
    if detail == "按浓度定容仅支持单一溶剂行":
        return "Concentration-based volume calculation supports only one solvent row."
    if detail.startswith("组分 ") and "）的 SMILES 无法解析：" in detail:
        left, smiles = detail.split("）的 SMILES 无法解析：", 1)
        middle = left[len("组分 "):]
        if "（" in middle:
            index, role = middle.split("（", 1)
            return f"Component {index} ({role}) has an unparseable SMILES: {smiles}"
    return "Stoichiometry input is invalid."


def _skill_error_message(exc: Exception) -> str:
    name = type(exc).__name__
    detail = str(getattr(exc, "detail", "") or "")
    if name == "SkillNotAccessibleError":
        return "Skill not found or not accessible."
    if name == "SkillCategoryError":
        return "The requested skill category does not exist or is disabled."
    if name == "SkillSlugConflictError":
        return "A skill with the same slug already exists for this user."
    if name == "MissingSkillIdempotencyKeyError":
        return "idempotency_key is required for authenticated skill creation."
    if name == "SkillIdempotencyKeyTooLongError":
        return "idempotency_key must not exceed 200 characters."
    if name == "SkillArchiveValidationError":
        kind = getattr(exc, "kind", "")
        tail = detail.split("：", 1)[1].strip() if "：" in detail else ""
        if kind == "archive_too_large":
            return "The skill archive exceeds the allowed ZIP size."
        if kind == "invalid_archive":
            return "The supplied file is not a valid ZIP archive."
        if kind == "unsafe_path":
            if detail.startswith("目录层级过深："):
                return f"Archive path is nested too deeply: {tail}"
            if detail.startswith("不允许符号链接："):
                return f"Symbolic links are not allowed in skill archives: {tail}"
            return f"Unsafe archive path: {tail}" if tail else "The skill archive contains an unsafe path."
        if kind == "decompression":
            return (
                f"Suspicious compression ratio detected for archive entry: {tail}"
                if tail else "The skill archive failed decompression safety checks."
            )
        if kind == "empty_archive":
            return "The skill archive contains no files."
        if kind == "archive_limit":
            if detail.startswith("文件数超过 "):
                value = detail[len("文件数超过 "):].split(" ", 1)[0]
                return f"The skill archive exceeds the {value}-file limit."
            if detail.startswith("解包后总量超过 "):
                value = detail[len("解包后总量超过 "):].split(" ", 1)[0]
                return f"The extracted skill archive exceeds the {value} total-size limit."
            if detail.startswith("单文件超过 "):
                rest = detail[len("单文件超过 "):]
                limit, _, path = rest.partition(" 上限：")
                return f"Archive entry {path} exceeds the {limit} per-file limit."
            return "The skill archive exceeds a file or content limit."
        if kind == "manifest_invalid":
            if detail == "压缩包根目录必须包含 SKILL.md":
                return "SKILL.md must exist at the root of the archive."
            if detail == "SKILL.md frontmatter 必须包含 name 和 description":
                return "SKILL.md frontmatter must include name and description."
            if detail.startswith("二进制文件只能放在 assets/ 或 examples/ 目录："):
                return f"Binary files are allowed only under assets/ or examples/: {tail}"
            if detail.startswith("技能名无法转为合法 slug："):
                return f"The skill name cannot be converted to a valid slug: {tail}"
            return "SKILL.md or its manifest metadata is invalid."
    return "The skill request could not be completed."


def _client_ip(headers: Any) -> str:
    """匿名限流分桶键: 取 x-forwarded-for 首段(nginx 注入), 缺省 unknown。"""
    if not headers:
        return "unknown"
    xff = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return "unknown"


async def _render_enter(actor: Actor | None, headers: Any = None) -> list[str]:
    """进入渲染闸门, 返回已持有租约的身份列表(交给 _render_exit 释放)。"""
    identity = f"actor:{actor.id}" if actor is not None else f"anon:{_client_ip(headers)}"
    held: list[str] = []
    try:
        if actor is None:
            # 匿名拆桶(按来源IP)后加全局兜底, 防分布式刷
            await rate_limit.enforce(MCP_RENDER_BUCKET, "anon-global", MCP_RENDER_ANON_GLOBAL_LIMIT, 60)
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
        # 统一转成 MCP ToolError(G2.R: core 已 neutral, 此处捕语义异常)。
        await rate_limit.release_leases(held, MCP_RENDER_BUCKET)
        raise ToolError(_rate_error_message(exc)) from exc


async def _render_exit(held: list[str]) -> None:
    await rate_limit.release_leases(held, MCP_RENDER_BUCKET)


# ---------------------------------------------------------------------------
# MCP serverInfo.version(B6)
# ---------------------------------------------------------------------------

def _release_version() -> str:
    """MCP serverInfo.version = 仓库根 VERSION(产品发布版本)。

    与 settings.api_version 不是同一版本轴: 后者是 HTTP API contract version
    (1.0.0), 保持不变。这里只读文件, 不硬编码第二份版本号。
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

def _bearer(headers: Any) -> str | None:
    """Extract Authorization header from MCP request context headers."""
    if not headers:
        return None
    value = headers.get("authorization") or headers.get("Authorization")
    if value and value.lower().startswith("bearer "):
        return value
    return None


async def _actor_from_headers(headers: Any) -> Actor | None:
    """Resolve Actor from Bearer token; None = anonymous (read-only tools)."""
    auth = _bearer(headers)
    if not auth:
        return None
    async with async_session() as session:
        actor = await resolve_actor(session, authorization=auth, session_token=None)
        return actor


def _require(actor: Actor | None, scope: str) -> Actor:
    if actor is None:
        raise ToolError("Authentication required. Connect an HGS AI Key with Authorization: Bearer <AI Key>.")
    if actor.auth_kind != "agent" and actor.auth_kind != "session":
        raise ToolError("Unsupported authentication type.")
    if actor.auth_kind == "agent" and scope not in actor.scopes:
        raise ToolError(f"The credential is missing the required scope: {scope}.")
    return actor


def _require_login(actor: Actor | None) -> Actor:
    """登录即可的操作(与 REST current_actor 同语义), 不做 scope 收紧."""
    if actor is None:
        raise ToolError("Authentication required. Connect an HGS AI Key with Authorization: Bearer <AI Key>.")
    return actor


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
        title="HGS AIchem MCP",
        # serverInfo.version = 产品发布版本(仓库根 VERSION), 不是 HTTP API
        # contract version(settings.api_version)。
        version=_release_version(),
        instructions=(
            "HGS provides chemical and reaction context, stoichiometry, reusable skills, "
            "and user-owned reaction records. Public tools may be used anonymously; "
            "structure search, private data, and write actions require authentication. "
            "Before creating a user-owned record, show the intended content to the user "
            "and obtain confirmation. New reactions should default to private. Never "
            "invent structures, identifiers, sources, conditions, or yields. Preserve "
            "source-specific values and provenance when evidence differs."
        ),
    )

    # ---------------- 查询与读取工具 ----------------

    @server.tool(name="search_chemistry_data", title="Search chemistry data", annotations=ANN_SEARCH_OPEN)
    async def search_chemistry_data(
        q: str,
        mode: str = "exact",
        threshold: float = 0.7,
        page: int = 1,
        page_size: int = 30,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Search chemicals and reactions by name, CAS, HCID, PubChem CID, InChIKey,
        DOI, SMILES, substructure, or similarity.

        mode: exact (default), substructure, or similarity.
        threshold: similarity cutoff from 0.4 to 1.0 (default 0.7).
        total=None means a complete total was not computed for this search mode.
        has_more is authoritative for pagination; do not infer it from total.
        capped=true can occur for substructure search when the 250-result product
        cap is reached. In that case the database-wide match count is unknown.
        """
        if mode not in ("exact", "substructure", "similarity"):
            raise ToolError("mode must be one of: exact, substructure, similarity.")
        q = (q or "").strip()
        if not q or len(q) > 4000:
            raise ToolError("q is required and must not exceed 4000 characters.")
        page = min(max(page, 1), 20)
        page_size = min(max(page_size, 1), 100)
        # threshold 3位小数契约(与 REST routes.py 0914 #6 同口径): 不round则
        # 0.70004 穿透到 REST 层吃 422, 错误信息对 MCP 客户端不可解。
        threshold = round(min(max(threshold, 0.4), 1.0), 3)
        # 结构检索登录墙与 REST 一致: mode!=exact 需 Bearer token, 匿名 ToolError.
        # exact 保持原样(匿名, 不透传 actor).
        actor = None
        if mode != "exact":
            actor = await _actor_from_headers(ctx.headers if ctx else None)
            if actor is None:
                raise ToolError("Substructure and similarity search require authentication; exact search is public.")
        # G2.3 final: 直调 shared search orchestration(services/search.py
        # execute_search)—— cache/结构闸门/canonicalize/查询/结果组装唯一 owner。
        # adapter 只保留: 参数验证/clamp、auth、会话获取、错误映射。
        from .services.search import SearchError as _SearchError
        from .services.search import execute_search as _execute_search
        from .core.rate_limit import RateLimitError as _RateLimitError

        async with async_session() as _session:
            try:
                return await _execute_search(
                    _session, q, mode, threshold=threshold, page=page,
                    page_size=page_size,
                    actor_id=actor.id if actor else None,
                )
            except _SearchError as exc:
                raise ToolError(_search_error_message(exc)) from exc
            except RateLimitError as exc:
                raise ToolError(_rate_error_message(exc)) from exc

    @server.tool(name="get_chemical", title="Get chemical", annotations=ANN_CHEMICAL_OPEN)
    async def get_chemical(
        chemical_id: int,
        enrich: str = "core",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Return chemical context for one HCID.

        enrich=core returns the canonical projection without provider access.
        enrich=full adds unified semantic detail: descriptions, names, properties,
        safety, industrial context, suppliers, and provenance. Source-specific
        values remain distinct and retain their source attribution.
        """
        if enrich not in ("core", "full"):
            raise ToolError("enrich must be either core or full.")
        if not 1 <= chemical_id <= 2_147_483_647:
            raise ToolError("chemical_id is out of range.")
        # G2.4B: 直调 shared detail orchestration(services/chemicals)。
        # auth 行为冻结: 恒匿名(actor 不解析), priority=50 与基线一致。
        from .services.chemicals import (
            ChemicalNotFoundError as _ChemicalNotFoundError,
            get_chemical_detail as _get_chemical_detail,
            normalize_enrich as _normalize_enrich,
        )

        async with async_session() as session:
            try:
                return await _get_chemical_detail(
                    session, chemical_id,
                    actor_id=None, priority=50,
                    enrich=_normalize_enrich(enrich),
                )
            except _ChemicalNotFoundError as exc:
                raise ToolError("Chemical not found.") from exc

    @server.tool(name="get_reaction", title="Get reaction", annotations=ANN_READ_CLOSED)
    async def get_reaction(
        reaction_id: int,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Return one reaction by HRID. With an authenticated credential, the owner may
        also read their own private reaction record."""
        from .services.reactions import load_reaction_detail

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if not 1 <= reaction_id <= 2_147_483_647:
            raise ToolError("reaction_id is out of range.")
        # G2.5B: 直调 transport-neutral service(None=不存在或不可见);
        # auth 行为冻结: 无/无效 credential → anonymous(viewer_id=0)。
        async with async_session() as session:
            data = await load_reaction_detail(
                session, reaction_id,
                viewer_id=actor.id if actor else 0,
                viewer_is_admin=bool(actor and actor.role == "admin"),
            )
            if data is None:
                raise ToolError("Reaction not found.")
            return data

    @server.tool(name="render_molecule_svg", title="Render molecule SVG", annotations=ANN_READ_CLOSED)
    async def render_molecule_svg(
        chemical_id: int | None = None,
        smiles: str | None = None,
        width: int = 400,
        height: int = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """Render a 2D molecular structure as SVG text.

        Provide either chemical_id for an HGS chemical or smiles for a direct
        structure (maximum 512 characters). width and height are clamped to
        50-800 pixels.
        """
        from .services import rendering as render_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        width = min(max(width, 50), 800)
        height = min(max(height, 50), 800)
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
            if len(target_smiles) > 512:
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

    @server.tool(name="render_reaction_svg", title="Render reaction SVG", annotations=ANN_READ_CLOSED)
    async def render_reaction_svg(
        reaction_id: int,
        width: int = 800,
        height: int = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """Render a reaction equation as SVG text.

        width and height are clamped to 50-800 pixels. The default output size is
        800×300.
        """
        from .services import rendering as render_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        width = min(max(width, 50), 800)
        height = min(max(height, 50), 800)
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

    @server.tool(name="list_skills", title="List skills", annotations=ANN_READ_CLOSED)
    async def list_skills(
        scope: str = "public",
        q: str = "",
        category: str = "",
        page: int = 1,
        page_size: int = 30,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """List reusable skills. scope=public is available anonymously; scope=mine
        requires authentication and returns the caller's own skills."""
        from .services.skills import list_skills as _list_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if scope not in ("public", "mine"):
            raise ToolError("scope must be either public or mine.")
        if scope == "mine":
            # 与 REST 契约一致: list_skills(mine) 仅要求登录, scope 收紧在 handler 内不发生.
            actor = _require_login(actor)
        q = (q or "")[:120]
        category = (category or "")[:40]
        page = min(max(page, 1), 500)
        page_size = min(max(page_size, 1), 100)
        # G2.6B: 直调 shared service(skill.query.list kernel)。
        async with async_session() as session:
            return await _list_service(
                session, scope=scope, owner_id=actor.id if scope == "mine" else None,
                q=q, category=category, page=page, page_size=page_size,
            )

    @server.tool(name="get_skill", title="Get skill", annotations=ANN_READ_CLOSED)
    async def get_skill(
        skill_id: int | str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Return a skill manifest, file list, and full SKILL.md text.

        skill_id accepts either a numeric ID or a slug such as
        huagongshe-reaction-publisher. Binary file contents are not returned.
        """
        from .services.skills import SkillNotAccessibleError
        from .services.skills import get_skill_detail as _detail_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if isinstance(skill_id, str):
            candidate = skill_id.strip()
            if candidate.isdigit():
                resolved_id = int(candidate)
            else:
                resolved_id = await _resolve_skill_slug(candidate, actor)
        else:
            resolved_id = skill_id
        if not 1 <= resolved_id <= 2_147_483_647:
            raise ToolError("skill_id is out of range.")
        # G2.6C: 直调 shared detail service(slug 解析留本 adapter);
        # missing/private-unreadable → 同一 ToolError 原文。
        async with async_session() as session:
            try:
                return await _detail_service(
                    session, resolved_id,
                    actor_id=actor.id if actor else None)
            except SkillNotAccessibleError as exc:
                raise ToolError(_skill_error_message(exc)) from exc

    @server.tool(name="calculate_stoichiometry", title="Calculate stoichiometry", annotations=ANN_READ_CLOSED)
    async def calculate_stoichiometry(
        components: list[dict[str, Any]],
        basis: dict[str, Any],
        concentration_mol_per_l: float | None = None,
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
        # 限流桶与 REST 同构(登录=u{id} 桶, 匿名=anon 桶) —— G2.1 起 MCP
        # 直调 transport-neutral service, 限流作为 entrypoint policy 在本
        # adapter 显式执行, 与 HTTP adapter 同桶同身份方案(行为不变)。
        _identity = f"u{actor.id}" if actor else "anon"
        # 限流(RateLimited/LimiterUnavailable)与业务校验(ValueError)都在
        # MCP 边界转成 ToolError —— 客户端可读 detail 原文(G2.R: 捕 neutral
        # 语义异常, 不再捕 FastAPI HTTPException)。
        try:
            await _rate_limit.enforce("stoich", _identity,
                                      _settings.api_stoich_limit_per_minute, 60)
            return await stoich_service.compute(body)
        except ValueError as exc:
            raise ToolError(_stoichiometry_error_message(exc)) from exc
        except _RateLimitError as exc:
            raise ToolError(_rate_error_message(exc)) from exc

    # ---------------- 写工具(需要 AI Key) ----------------

    @server.tool(name="list_my_reactions", title="List my reactions", annotations=ANN_READ_CLOSED)
    async def list_my_reactions(
        visibility: str = "all",
        page: int = 1,
        page_size: int = 20,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """List reaction records owned by the authenticated HGS user."""
        from .services.reactions import list_my_reactions as _list_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        # 与 REST 契约一致(agent-guide: bearer 即可), 不做额外 scope 收紧.
        actor = _require_login(actor)
        if visibility not in ("all", "public", "private"):
            raise ToolError("visibility must be one of: all, public, private.")
        page = min(max(page, 1), 500)
        page_size = min(max(page_size, 1), 50)
        # G2.5C: 直调 shared service(clamp 保持, 不改 ToolError/拒绝).
        async with async_session() as session:
            return await _list_service(
                session, actor_id=actor.id, visibility=visibility,
                page=page, page_size=page_size,
            )

    @server.tool(name="validate_reaction", title="Validate reaction draft", annotations=ANN_READ_CLOSED)
    async def validate_reaction(
        reaction: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """Validate and canonicalize a reaction draft without saving it.

        Requires reaction:write permission.
        """
        from .core.rate_limit import RateLimitError as _RateLimitError
        from .services.reactions import ReactionValidationError
        from .services.reactions import validate_reaction_draft

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "reaction:write")
        try:
            body = ReactionBody(**reaction)
        except Exception as exc:
            raise ToolError(_validation_error_message("Invalid reaction draft fields", exc)) from exc
        # G3.1B: 直调 shared validation service(A005 validate 关闭);
        # neutral validation/rate error → ToolError(detail)。
        try:
            return await validate_reaction_draft(
                actor_id=actor.id, body=body)
        except ReactionValidationError as exc:
            raise ToolError(_reaction_error_message(exc)) from exc
        except _RateLimitError as exc:
            raise ToolError(_rate_error_message(exc)) from exc

    @server.tool(name="validate_skill", title="Validate skill package", annotations=ANN_READ_CLOSED)
    async def validate_skill(
        zip_base64: str,
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

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "skill:write")
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

    @server.tool(name="create_skill", title="Create skill", annotations=ANN_CREATE_CLOSED)
    async def create_skill(
        zip_base64: str,
        category: str | None = None,
        idempotency_key: str = "",
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

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "skill:write")
        # G3.1D 冻结 ordering: base64 decode 在 service/rate 之前
        # (非法 base64 不消耗 quota, service 零调用)。
        try:
            raw = _base64.b64decode(zip_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("zip_base64 is not valid base64.") from exc

        async def _archive_loader(limit: int) -> bytes:
            # 原 read(limit) slicing 语义逐字保持。
            return raw[:limit]

        try:
            # G3.1D: 直调 shared create service(handler-call A005 关闭);
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

    @server.tool(name="create_reaction", title="Create reaction", annotations=ANN_CREATE_OPEN)
    async def create_reaction(
        reaction: dict[str, Any],
        idempotency_key: str,
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

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "reaction:write")
        # G3.1C 冻结差异: MCP 侧 idempotency_key 必填且 ≤200, 检查在
        # service/rate 之前(service 不被调, quota 不消耗)。
        if not idempotency_key or len(idempotency_key) > 200:
            raise ToolError("idempotency_key is required and must not exceed 200 characters.")
        try:
            body = ReactionBody(**reaction)
        except Exception as exc:
            raise ToolError(f"Invalid draft fields: {exc}") from exc
        try:
            # G3.1C: 直调 shared create service(A005 create 关闭);
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
            # E9-B: CONFLICT/AMBIGUOUS → no rows created.
            raise ToolError(_reaction_error_message(exc)) from exc

    return server


# ---------------------------------------------------------------------------
# FastAPI 集成
# ---------------------------------------------------------------------------

_mcp_server: MCPServer | None = None


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
        host="0.0.0.0",
    )
    # 2026-08-31 终局: 挂根 + 子路径 /mcp → MCP 端点 = /mcp(规范路径, 关键路由锁死)。
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
