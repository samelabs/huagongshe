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


def _render_busy() -> ToolError:
    return ToolError("渲染并发已达上限，请稍后重试")


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
        raise ToolError(exc.detail) from exc


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
        raise ToolError("此操作需要 AI Key：在网页 账户设置 → AI Key 生成后以 Authorization: Bearer <AI Key> 连接")
    if actor.auth_kind != "agent" and actor.auth_kind != "session":
        raise ToolError("身份类型不支持")
    if actor.auth_kind == "agent" and scope not in actor.scopes:
        raise ToolError(f"AI Key 缺少 {scope} 权限")
    return actor


def _require_login(actor: Actor | None) -> Actor:
    """登录即可的操作(与 REST current_actor 同语义), 不做 scope 收紧."""
    if actor is None:
        raise ToolError("此操作需要 AI Key：在网页 账户设置 → AI Key 生成后以 Authorization: Bearer <AI Key> 连接")
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
        raise ToolError(f"slug 不存在或不可访问: {candidate!r}")
    if len(rows) > 1:
        raise ToolError(
            f"slug {candidate!r} 存在多个可访问技能，请改用 numeric skill_id 指定"
        )
    return int(rows[0])


def build_mcp_server() -> MCPServer:
    server = MCPServer(
        name="huagongshe-aichem",
        title="化工社AIchem MCP",
        # serverInfo.version = 产品发布版本(仓库根 VERSION), 不是 HTTP API
        # contract version(settings.api_version)。
        version=_release_version(),
        instructions=(
            "你是化工社AIchem助手：查询化合物与反应数据、计算投料、保存反应记录。"
            "部分公开工具可匿名使用；访问个人数据、结构检索及受授权操作需要 AI Key。"
            "保存前必须先向用户展示草稿并取得确认；新记录默认 private。"
            "不得编造 SMILES、来源、条件或收率。"
        ),
    )

    # ---------------- 查询与读取工具 ----------------

    @server.tool(name="search_chemistry_data", title="统一搜索")
    async def search_chemistry_data(
        q: str,
        mode: str = "exact",
        threshold: float = 0.7,
        page: int = 1,
        page_size: int = 30,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """按名称、CAS、HCID、CID、InChIKey、DOI、SMILES 或结构查询化合物和反应。

        mode: exact(默认) / substructure / similarity。
        threshold: similarity 模式阈值(0.4-1.0, 默认 0.7), 与 REST 同语义。
        total=None 表示当前查询模式未计算完整 total；has_more 是下一页是否存在
        的权威字段(不要用 total 反推是否还有下一页)。
        capped=true 仅 substructure 模式出现: 已达产品返回上限(250), 数据库
        真实总匹配数未知 — 此时 total 不是数据库真实总数, 不得如此描述。
        """
        if mode not in ("exact", "substructure", "similarity"):
            raise ToolError("mode 只能是 exact、substructure 或 similarity")
        q = (q or "").strip()
        if not q or len(q) > 4000:
            raise ToolError("q 必填且不超过 4000 字符")
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
                raise ToolError("结构检索（子结构/相似度）需要 AI Key；exact 模式可匿名使用")
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
                raise ToolError(exc.detail) from exc
            except RateLimitError as exc:
                raise ToolError(exc.detail) from exc

    @server.tool(name="get_chemical", title="化合物详情")
    async def get_chemical(
        chemical_id: int,
        enrich: str = "core",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个 HCID 的结构、标识符、性质和关联反应概况。"""
        if enrich not in ("core", "full"):
            raise ToolError("enrich 只能是 core 或 full")
        if not 1 <= chemical_id <= 2_147_483_647:
            raise ToolError("chemical_id 超出范围")
        # G2.4B: 直调 shared detail orchestration(services/chemicals)。
        # auth 行为冻结: 恒匿名(actor 不解析), priority=50 与基线一致。
        from .services.chemicals import (
            ChemicalNotFoundError as _ChemicalNotFoundError,
            get_chemical_detail as _get_chemical_detail,
        )

        async with async_session() as session:
            try:
                return await _get_chemical_detail(
                    session, chemical_id,
                    actor_id=None, priority=50,
                )
            except _ChemicalNotFoundError as exc:
                raise ToolError(str(exc)) from exc

    @server.tool(name="get_chemical_externals", title="化合物中文扩展")
    async def get_chemical_externals(
        chemical_id: int,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个 HCID 的中文扩展条目(物化性质/安全/应用/制备/上下游)与供应商列表。"""
        from .services.cb import (
            ChemicalExternalsNotFoundError as _ChemicalExternalsNotFoundError,
            get_chemical_externals as _get_chemical_externals,
        )

        if not 1 <= chemical_id <= 2_147_483_647:
            raise ToolError("chemical_id 超出范围")
        # G2.4C: 直调 shared externals orchestration(services/cb)。
        # auth 行为冻结: 恒匿名(actor 不解析) → anonymous-global 30/min。
        async with async_session() as session:
            try:
                return await _get_chemical_externals(
                    session, chemical_id, actor_id=None,
                )
            except _ChemicalExternalsNotFoundError as exc:
                raise ToolError(str(exc)) from exc
            except RateLimitError as exc:
                raise ToolError(exc.detail) from exc

    @server.tool(name="get_reaction", title="反应详情")
    async def get_reaction(
        reaction_id: int,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个 HRID。携带 Token 时也可读取自己的私有记录。"""
        from .services.reactions import load_reaction_detail

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if not 1 <= reaction_id <= 2_147_483_647:
            raise ToolError("reaction_id 超出范围")
        # G2.5B: 直调 transport-neutral service(None=不存在或不可见);
        # auth 行为冻结: 无/无效 credential → anonymous(viewer_id=0)。
        async with async_session() as session:
            data = await load_reaction_detail(
                session, reaction_id,
                viewer_id=actor.id if actor else 0,
                viewer_is_admin=bool(actor and actor.role == "admin"),
            )
            if data is None:
                raise ToolError("反应不存在")
            return data

    @server.tool(name="render_molecule_svg", title="分子结构图")
    async def render_molecule_svg(
        chemical_id: int | None = None,
        smiles: str | None = None,
        width: int = 400,
        height: int = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """获取化合物的 2D 结构图(SVG 文本)，width/height 指定像素尺寸(50-800)。
        chemical_id(库内化合物)或 smiles(任意结构)二选一。"""
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
                raise ToolError("化合物不存在或没有可渲染的结构表达")
        elif smiles:
            target_smiles = smiles.strip()
            # 外部直传 SMILES 的 resource bound: 实测 ~4000 字符合法
            # SMILES 可让 RDKit render 占分钟级 CPU。512 只管用户直传;
            # chemical_id 路径的 SMILES 来自 DB(受写入校验), 不套用。
            # guard 必须在 RDKit 之前。
            if len(target_smiles) > 512:
                raise ToolError("SMILES 不能超过 512 字符")
        else:
            raise ToolError("需要 chemical_id 或 smiles 参数(二选一)")
        if not target_smiles:
            raise ToolError("没有可渲染的结构表达")
        import asyncio as _asyncio

        # 资源闸门在 RDKit to_thread 之前; 与 render_reaction_svg 共用同一池。
        held = await _render_enter(actor, ctx.headers if ctx else None)
        try:
            svg = await _asyncio.to_thread(render_service.smiles_to_svg, target_smiles, width, height)
        finally:
            await _render_exit(held)
        if svg is None:
            raise ToolError("SMILES 无法渲染")
        return svg

    @server.tool(name="render_reaction_svg", title="反应方程式图")
    async def render_reaction_svg(
        reaction_id: int,
        width: int = 1200,
        height: int = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """获取反应方程式的 2D 结构图(SVG 文本)。"""
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
            raise ToolError("反应不存在或没有可渲染的表达")
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
            raise ToolError("反应 SMILES 无法渲染")
        return svg

    @server.tool(name="list_skills", title="技能列表")
    async def list_skills(
        scope: str = "public",
        q: str = "",
        category: str = "",
        page: int = 1,
        page_size: int = 30,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """列出技能。scope=public 匿名可用; scope=mine 需要 AI Key。"""
        from . import skills as skills_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if scope not in ("public", "mine"):
            raise ToolError("scope 只能是 public 或 mine")
        if scope == "mine":
            # 与 REST 契约一致: list_skills(mine) 仅要求登录, scope 收紧在 handler 内不发生.
            actor = _require_login(actor)
        q = (q or "")[:120]
        category = (category or "")[:40]
        page = min(max(page, 1), 500)
        page_size = min(max(page_size, 1), 100)
        async with async_session() as session:
            return await skills_module.list_skills(
                scope=scope, q=q, category=category, page=page, page_size=page_size,
                actor=actor, db=session,
            )

    @server.tool(name="get_skill", title="技能详情")
    async def get_skill(
        skill_id: int | str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个技能的 manifest、文件清单和 SKILL.md 全文(文本文件不含二进制)。
        skill_id 支持数字 id 或 slug 字符串(如 huagongshe-reaction-publisher)。"""
        from . import skills as skills_module

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
            raise ToolError("skill_id 超出范围")
        async with async_session() as session:
            return await skills_module.get_skill(skill_id=resolved_id, actor=actor, db=session)

    @server.tool(name="calculate_stoichiometry", title="投料计算")
    async def calculate_stoichiometry(
        components: list[dict[str, Any]],
        basis: dict[str, Any],
        concentration_mol_per_l: float | None = None,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """投料计算：角色化组分 + 基准投料量 → 整表投料量/理论收率/溶剂定容。

        components[{role(REACTANT/REAGENT/CATALYST/SOLVENT/PRODUCT), smiles, eq, label?}]
        basis{index, amount_value, amount_unit(g/mg/mol/mmol)}。
        非溶剂组分 eq 必填；最多 30 个组分。

        示例(arguments): {"components":[{"role":"REACTANT","smiles":"O=C(O)c1ccccc1O","eq":1},{"role":"REAGENT","smiles":"CC(=O)OC(=O)C","eq":1.05},{"role":"PRODUCT","smiles":"CC(=O)Oc1ccccc1C(=O)O","eq":1}],"basis":{"index":0,"amount_value":10,"amount_unit":"g"}}
        """
        from .core import rate_limit as _rate_limit
        from .core.rate_limit import RateLimitError as _RateLimitError
        from .core.config import settings as _settings
        from .services import stoichiometry as stoich_service

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        body = ScaleInput(
            components=components, basis=basis,
            concentration_mol_per_l=concentration_mol_per_l,
        )
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
            raise ToolError(str(exc)) from exc
        except _RateLimitError as exc:
            raise ToolError(exc.detail) from exc

    # ---------------- 写工具(需要 AI Key) ----------------

    @server.tool(name="list_my_reactions", title="我的反应")
    async def list_my_reactions(
        visibility: str = "all",
        page: int = 1,
        page_size: int = 20,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取 AI Key 所属用户自己的反应记录(需 AI Key)。"""
        from . import reactions as reactions_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        # 与 REST 契约一致(agent-guide: bearer 即可), 不做额外 scope 收紧.
        actor = _require_login(actor)
        if visibility not in ("all", "public", "private"):
            raise ToolError("visibility 只能是 all、public 或 private")
        page = min(max(page, 1), 500)
        page_size = min(max(page_size, 1), 50)
        async with async_session() as session:
            return await reactions_module.my_reactions(
                visibility=visibility, page=page, page_size=page_size,
                actor=actor, db=session,
            )

    @server.tool(name="validate_reaction", title="校验反应草稿")
    async def validate_reaction(
        reaction: dict[str, Any],
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """校验反应草稿(RDKit 标准化, 不保存)。需要 reaction:write 权限的 Token。"""
        from fastapi import HTTPException as _HTTPException

        from . import reactions as reactions_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "reaction:write")
        try:
            body = ReactionBody(**reaction)
        except Exception as exc:
            raise ToolError(f"草稿字段不合法: {exc}") from exc
        try:
            return await reactions_module.validate_reaction(body=body, actor=actor)
        except _HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc

    @server.tool(name="validate_skill", title="校验技能包")
    async def validate_skill(
        zip_base64: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """校验技能 zip 草稿(不保存): 结构、配额、frontmatter、脚本语法与危险调用警告。

        zip_base64: 技能 zip 文件的 base64 编码(上限 10MB 解码后)。
        """
        import asyncio as _asyncio
        import base64 as _base64
        import binascii

        from fastapi import HTTPException as _HTTPException

        from . import skills as skills_module
        from .core.config import settings as _settings

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "skill:write")
        try:
            raw = _base64.b64decode(zip_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("zip_base64 不是合法的 base64") from exc
        if len(raw) > _settings.skill_zip_max_bytes:
            raise ToolError(f"压缩包超过 {_settings.skill_zip_max_bytes // (1024 * 1024)}MB 上限")
        try:
            manifest = await _asyncio.to_thread(skills_module.extract_skill_zip, raw)
            return {
                "ok": True,
                "slug": manifest["slug"], "title": manifest["title"],
                "description": manifest["description"], "license": manifest["license"],
                "has_scripts": manifest["has_scripts"],
                "file_count": manifest["file_count"], "size_bytes": manifest["size_bytes"],
                "warnings": manifest["warnings"],
                "files": [{"path": p, "size_bytes": len(d)} for p, d in manifest["files"]],
            }
        except _HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc

    @server.tool(name="create_skill", title="保存技能")
    async def create_skill(
        zip_base64: str,
        category: str | None = None,
        idempotency_key: str = "",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """把用户确认后的技能 zip 保存到该用户的技能容器(需 skill:write Token)。

        个人技能恒为 private。idempotency_key: 同一次保存的重试复用，其他技能不得复用。
        """
        import base64 as _base64
        import binascii

        from fastapi import HTTPException as _HTTPException

        from . import skills as skills_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "skill:write")
        try:
            raw = _base64.b64decode(zip_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError("zip_base64 不是合法的 base64") from exc

        class _FakeUpload:
            async def read(self, limit: int = -1):
                return raw if limit < 0 else raw[:limit]

        try:
            async with async_session() as session:
                return await skills_module.create_skill(
                    file=_FakeUpload(),  # type: ignore[arg-type]
                    category=(category or None),
                    request_idempotency_key=(idempotency_key or None),
                    actor=actor, db=session,
                )
        except _HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc

    @server.tool(name="create_reaction", title="保存反应")
    async def create_reaction(
        reaction: dict[str, Any],
        idempotency_key: str,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """保存用户确认后的反应记录(需 reaction:write Token + Idempotency-Key)。

        必须先用 validate_reaction 校验并让用户确认草稿后再调用；visibility 默认 private。
        成功返回 HRID、页面链接和新建 HCID。
        """
        from fastapi import HTTPException as _HTTPException

        from . import reactions as reactions_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        _require(actor, "reaction:write")
        if not idempotency_key or len(idempotency_key) > 200:
            raise ToolError("idempotency_key 必填且不超过 200 字符")
        try:
            body = ReactionBody(**reaction)
        except Exception as exc:
            raise ToolError(f"草稿字段不合法: {exc}") from exc
        try:
            # request 参数在 handler 体内未使用(已核实), 直调传 None;
            # enforce(actor.id 桶)+幂等检查在 handler 内原样生效.
            async with async_session() as session:
                return await reactions_module.create_reaction(
                    body=body, request=None,  # type: ignore[arg-type]
                    idempotency_key=idempotency_key, actor=actor, db=session,
                )
        except _HTTPException as exc:
            raise ToolError(str(exc.detail)) from exc

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
