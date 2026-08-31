"""MCP server: the agent-facing capability surface (M1).

设计锚点(全部基于已核实事实):
- mcp SDK 2.1.1: MCPServer + streamable_http_app() -> Starlette, mount 进 FastAPI.
- pm2 --workers 2: 必须 stateless_http=True(有状态 session 绑单 worker 内存,
  nginx 轮询跨 worker 必 404). stateless = 每请求独立 context.
- 认证: 不用 SDK token_verifier(它是传输层全量强制门, 匿名 initialize 都过不去,
  与"匿名只读 + Token 写"分层冲突). 每工具从 ctx.headers 读 Authorization,
  走 resolve_actor(与 REST 同一张 user_api_tokens 表, 同一套 scopes).
- DNS rebinding 防护: host 默认 127.0.0.1 会触发 localhost-only Host 校验,
  挂在公网域名后必 403 — 传 transport_security 显式关闭(nginx 层已有真实边界).
- 工具面 = agent-guide operations 一比一白名单映射, 硬编码, 不自动发现.
- thin wrapper 直调服务层函数(与 REST handler 共享同一函数), 不自调 HTTP.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from sqlalchemy import text

from .core.config import settings
from .core.database import async_session
from .schemas.reactions import ReactionBody
from .core.security import Actor, resolve_actor
from .schemas.stoichiometry import ScaleInput

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
        raise ToolError("此操作需要 API Token：在网页 账户设置 → AI 授权 生成后以 Authorization: Bearer *** 连接")
    if actor.auth_kind != "agent" and actor.auth_kind != "session":
        raise ToolError("身份类型不支持")
    if actor.auth_kind == "agent" and scope not in actor.scopes:
        raise ToolError(f"API Token 缺少 {scope} 权限")
    return actor


def _require_login(actor: Actor | None) -> Actor:
    """登录即可的操作(与 REST current_actor 同语义), 不做 scope 收紧."""
    if actor is None:
        raise ToolError("此操作需要 API Token：在网页 账户设置 → AI 授权 生成后以 Authorization: Bearer *** 连接")
    return actor


def build_mcp_server() -> MCPServer:
    server = MCPServer(
        name="huagongshe-aichem",
        title="化工社AIchem MCP",
        version=settings.api_version,
        instructions=(
            "你是化工社AIchem助手：查询化合物与反应数据、计算投料、保存反应记录。"
            "读工具匿名可用；写工具(校验/保存反应)需要 API Token。"
            "保存前必须先向用户展示草稿并取得确认；新记录默认 private。"
            "不得编造 SMILES、来源、条件或收率。"
        ),
    )

    # ---------------- 读工具(匿名可用) ----------------

    @server.tool(name="search_chemistry_data", title="统一搜索")
    async def search_chemistry_data(
        q: str,
        mode: str = "exact",
        page: int = 1,
        page_size: int = 30,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """按名称、CAS、HCID、CID、InChIKey、DOI、SMILES 或结构查询化合物和反应。

        mode: exact(默认) / substructure / similarity。返回 total(可能为 None 表示更多结果)与分页结果。
        """
        from . import routes as routes_module

        if mode not in ("exact", "substructure", "similarity"):
            raise ToolError("mode 只能是 exact、substructure 或 similarity")
        q = (q or "").strip()
        if not q or len(q) > 4000:
            raise ToolError("q 必填且不超过 4000 字符")
        page = min(max(page, 1), 20)
        page_size = min(max(page_size, 1), 100)
        # 结构检索登录墙与 REST 一致: mode!=exact 需 Bearer token, 匿名 ToolError.
        # exact 保持原样(匿名, 不透传 actor).
        actor = None
        if mode != "exact":
            actor = await _actor_from_headers(ctx.headers if ctx else None)
            if actor is None:
                raise ToolError("结构检索（子结构/相似度）需要 API Token；exact 模式可匿名使用")
        async with async_session() as session:
            return await routes_module.search(
                actor=actor, q=q, mode=mode, page=page, page_size=page_size, db=session
            )

    @server.tool(name="get_chemical", title="化合物详情")
    async def get_chemical(
        chemical_id: int,
        enrich: str = "core",
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个 HCID 的结构、标识符、性质和关联反应概况。"""
        from . import routes as routes_module

        if enrich not in ("core", "full"):
            raise ToolError("enrich 只能是 core 或 full")
        if not 1 <= chemical_id <= 2_147_483_647:
            raise ToolError("chemical_id 超出范围")
        async with async_session() as session:
            # request=None: enqueue_chemical_if_needed 仅在 request 非 None 且非 loopback
            # 时短路(公网只读); None = 不过短路 → 入队, 与 REST 经 BFF(loopback)行为一致.
            return await routes_module.chemical_detail(
                request=None,  # type: ignore[arg-type]
                chemical_id=chemical_id,
                enrich=enrich,
                display=False,
                actor=None,
                db=session,
            )

    @server.tool(name="get_chemical_externals", title="化合物中文扩展")
    async def get_chemical_externals(
        chemical_id: int,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个 HCID 的中文扩展条目(物化性质/安全/应用/制备/上下游)与供应商列表。"""
        from . import routes as routes_module

        if not 1 <= chemical_id <= 2_147_483_647:
            raise ToolError("chemical_id 超出范围")
        async with async_session() as session:
            return await routes_module.chemical_externals(
                request=None,  # type: ignore[arg-type]
                chemical_id=chemical_id,
                actor=None,
                db=session,
            )

    @server.tool(name="get_reaction", title="反应详情")
    async def get_reaction(
        reaction_id: int,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个 HRID。携带 Token 时也可读取自己的私有记录。"""
        from . import routes as routes_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if not 1 <= reaction_id <= 2_147_483_647:
            raise ToolError("reaction_id 超出范围")
        async with async_session() as session:
            return await routes_module.reaction_detail(
                reaction_id=reaction_id, actor=actor, db=session
            )

    @server.tool(name="render_molecule_svg", title="分子结构图")
    async def render_molecule_svg(
        chemical_id: int,
        width: int = 400,
        height: int = 300,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> str:
        """获取化合物的 2D 结构图(SVG 文本)，width/height 指定像素尺寸(50-800)。"""
        from . import mol as mol_module

        width = min(max(width, 50), 800)
        height = min(max(height, 50), 800)
        async with async_session() as session:
            row = (await session.execute(text(
                "SELECT smiles FROM chemistry.chemicals WHERE id=:id"
            ), {"id": chemical_id})).fetchone()
        if not row or not row[0]:
            raise ToolError("化合物不存在或没有可渲染的结构表达")
        import asyncio as _asyncio

        svg = await _asyncio.to_thread(mol_module.smiles_to_svg, row[0], width, height)
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
        from . import mol as mol_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        width = min(max(width, 50), 800)
        height = min(max(height, 50), 800)
        async with async_session() as session:
            row = (await session.execute(text("""
                SELECT reaction_smiles FROM chemistry.reactions
                WHERE id=:id AND reaction_smiles IS NOT NULL
                  AND (:is_admin OR created_by_user_id=:viewer_id
                       OR (visibility='public' AND moderation_status='visible'))
            """), {
                "id": reaction_id,
                "viewer_id": actor.id if actor else 0,
                "is_admin": bool(actor and actor.role == "admin"),
            })).fetchone()
        if not row or not row[0]:
            raise ToolError("反应不存在或没有可渲染的表达")
        import asyncio as _asyncio

        svg = await _asyncio.to_thread(mol_module.reaction_to_svg, row[0], width, height)
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
        """列出技能。scope=public 匿名可用; scope=mine 需要 Token。"""
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
        skill_id: int,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取一个技能的 manifest、文件清单和 SKILL.md 全文(文本文件不含二进制)。"""
        from . import skills as skills_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        if not 1 <= skill_id <= 2_147_483_647:
            raise ToolError("skill_id 超出范围")
        async with async_session() as session:
            return await skills_module.get_skill(skill_id=skill_id, actor=actor, db=session)

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
        """
        from . import stoichiometry as stoich_module

        actor = await _actor_from_headers(ctx.headers if ctx else None)
        body = ScaleInput(
            components=components, basis=basis,
            concentration_mol_per_l=concentration_mol_per_l,
        )
        # actor 透传: 限流桶与 REST 同构(登录=u{id} 桶, 匿名=anon 桶).
        return await stoich_module.calculate_stoichiometry(body=body, actor=actor)

    # ---------------- 写工具(需要 Token) ----------------

    @server.tool(name="list_my_reactions", title="我的反应")
    async def list_my_reactions(
        visibility: str = "all",
        page: int = 1,
        page_size: int = 20,
        ctx: Context = None,  # type: ignore[assignment]
    ) -> dict[str, Any]:
        """读取 Token 所属用户自己的反应记录(需 API Token)。"""
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
