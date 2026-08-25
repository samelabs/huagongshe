"""Small self-describing connection surface for user-authorized AI clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text

from .config import settings
from .database import get_db
from .security import Actor, optional_actor


router = APIRouter(tags=["agent"])


def agent_connection_text(token: str) -> str:
    origin = settings.public_base_url.rstrip("/")
    return (
        "请连接化工社，帮助我查询化学数据、整理并保存反应记录。\n"
        f"连接地址：{origin}/api/agent-guide\n"
        f"访问令牌：{token}\n\n"
        "请仅将令牌作为 Authorization: Bearer <访问令牌> 发送给 huagongshe.com。"
        "先携带令牌读取连接地址，确认账号、可用操作、字段要求和安全规则，"
        "再按我接下来的任务查询或整理。只有在我确认草稿后才能保存；"
        "新记录默认 private，设为 public 前必须再次确认。"
        "保存成功后返回 HRID、页面地址、可见范围和新建的 HCID。"
    )


@router.get(
    "/agent-guide",
    operation_id="get_agent_connection_guide",
    summary="连接化工社并读取 AI 可用操作",
)
async def agent_guide(
    authorization: str | None = Header(default=None),
    actor: Actor | None = Depends(optional_actor),
    db=Depends(get_db),
):
    """Return the complete, bounded operation guide; a Bearer token also confirms its owner."""
    bearer_supplied = bool(authorization and authorization.lower().startswith("bearer "))
    if bearer_supplied and actor is None:
        raise HTTPException(401, "API Token 无效、已过期或已撤销")

    agent = actor if actor and actor.auth_kind == "agent" else None
    origin = settings.public_base_url.rstrip("/")
    api_base = f"{origin}/api"
    publisher_skill_id = await db.execute(text(
        "SELECT id FROM community.skills WHERE slug='huagongshe-reaction-publisher' LIMIT 1"
    ))
    publisher_skill_id = publisher_skill_id.scalar()
    skill_url = (
        f"{origin}/api/skills/{publisher_skill_id}"
        if publisher_skill_id is not None
        else f"{api_base}/skills?scope=public&q=reaction-publisher"
    )
    return {
        "api_version": settings.api_version,
        "api_base_url": api_base,
        "connection": {
            "status": "ready" if agent else "authorization_required",
            "account": (
                {
                    "id": agent.id,
                    "username": agent.username,
                    "display_name": agent.display_name,
                }
                if agent else None
            ),
            "instruction": (
                "连接已确认。只使用下列 operations；需要精确字段时再读取 OpenAPI。"
                if agent
                else "创建 AI 授权：登录 huagongshe.com → 账户设置 → AI 授权（/me/settings/api-tokens），生成 Token 后以 Authorization: Bearer *** 再次读取本入口以确认连接。"
            ),
        },
        "authentication": {
            "type": "bearer",
            "header": "Authorization: Bearer <用户创建的 API Token>",
            "scopes": list(agent.scopes) if agent else ["read", "reaction:write", "skill:write"],
            "token_handling": "Token 仅发送给 huagongshe.com，不写入公开提示词、代码、文件或日志。",
        },
        "discovery": {
            "openapi_url": f"{api_base}/openapi.json",
            "help_url": f"{origin}/guide",
            "optional_skill_url": skill_url,
            "instruction": "先从 operations 选择操作；只有需要精确请求或响应结构时才读取 OpenAPI。",
        },
        "operations": [
            {
                "id": "search_chemistry_data",
                "method": "GET",
                "path": "/api/search",
                "auth": "public_or_bearer",
                "purpose": "按名称、CAS、HCID、CID、InChIKey、DOI、SMILES 或结构查询化合物和反应",
                "input": "q 必填；mode 为 exact、substructure 或 similarity；page 默认1最大20；page_size 默认30最大100；返回 total 总数和分页结果",
            },
            {
                "id": "get_chemical",
                "method": "GET",
                "path": "/api/chemicals/{chemical_id}",
                "auth": "public_or_bearer",
                "purpose": "读取一个 HCID 的结构、标识符、性质和关联反应概况",
            },
            {
                "id": "get_chemical_externals",
                "method": "GET",
                "path": "/api/chemicals/{chemical_id}/externals",
                "auth": "public_or_bearer",
                "purpose": "读取一个 HCID 的中文扩展条目（基本信息/物化性质/安全数据/应用/制备/上下游）与供应商列表（纯度/包装价格/联系方式）；无 CAS 或无数据时 entry 与 suppliers 为空",
            },
            {
                "id": "get_reaction",
                "method": "GET",
                "path": "/api/reactions/{reaction_id}",
                "auth": "public_or_bearer",
                "purpose": "读取一个 HRID；Token 所属用户也可读取自己的私有记录",
            },
            {
                "id": "render_molecule_svg",
                "method": "GET",
                "path": "/api/mol/{chemical_id}/svg/{w}x{h}.svg",
                "auth": "public",
                "purpose": "获取化合物的 2D 结构图（SVG），w/h 指定尺寸",
            },
            {
                "id": "render_reaction_svg",
                "method": "GET",
                "path": "/api/reactions/{reaction_id}/svg/{w}x{h}.svg",
                "auth": "public",
                "purpose": "获取反应方程式的 2D 结构图（SVG），w/h 指定尺寸",
            },
            {
                "id": "list_my_reactions",
                "method": "GET",
                "path": "/api/users/me/reactions",
                "auth": "bearer",
                "purpose": "读取 Token 所属用户自己的反应记录",
                "input": "visibility 为 all、private 或 public；支持 page 和 page_size",
            },
            {
                "id": "list_skills",
                "method": "GET",
                "path": "/api/skills",
                "auth": "public_or_bearer",
                "purpose": "列出技能：scope=public 浏览平台公开技能池（含官方与开源社区技能），scope=mine 读取 Token 所属用户自己的技能",
                "input": "scope 为 public 或 mine（mine 需 Bearer）；q 关键词搜索；category 分类过滤；支持 page 和 page_size",
            },
            {
                "id": "get_skill",
                "method": "GET",
                "path": "/api/skills/{skill_id}",
                "auth": "public_or_bearer",
                "purpose": "读取一个技能的 manifest、文件树和 SKILL.md 全文；Token 所属用户也可读取自己的私有技能",
            },
            {
                "id": "download_skill_archive",
                "method": "GET",
                "path": "/api/skills/{skill_id}/archive",
                "auth": "public_or_bearer",
                "purpose": "下载技能完整 zip 包，用于在用户本地 AI 环境装载；含脚本的技能执行前必须人工审阅",
            },
            {
                "id": "calculate_stoichiometry",
                "method": "POST",
                "path": "/api/stoichiometry/scale",
                "auth": "public_or_bearer",
                "purpose": "投料计算：按角色列出反应全部组分，以任一组分（限量试剂或目标产物）的投料量为摩尔基准，换算整表投料量并给出产物理论收率",
                "input": "components[{role(REACTANT/REAGENT/CATALYST/SOLVENT/PRODUCT),smiles,eq,label?}]（最多30个，非溶剂 eq 必填）+ basis{index,amount_value,amount_unit(g/mg/mol/mmol)} + 可选 concentration_mol_per_l（溶剂按浓度定容只给体积）",
            },
            {
                "id": "validate_reaction",
                "method": "POST",
                "path": "/api/reactions/validate",
                "auth": "bearer:reaction:write",
                "purpose": "校验反应草稿并返回 RDKit 标准化后的 reaction SMILES 和参与物",
            },
            {
                "id": "validate_skill",
                "method": "POST",
                "path": "/api/skills/validate",
                "auth": "public_or_bearer",
                "purpose": "校验技能 zip 草稿（不保存）：结构、配额、文件数、frontmatter、脚本语法与危险调用警告",
                "input": "multipart 字段 file=<技能 zip>",
            },
            {
                "id": "create_skill",
                "method": "POST",
                "path": "/api/skills",
                "auth": "bearer:skill:write",
                "purpose": "把用户确认后的技能 zip 保存到该用户的技能容器；个人技能恒为 private",
                "required_header": "Idempotency-Key；同一次保存的重试复用，其他技能不得复用",
            },
            {
                "id": "create_reaction",
                "method": "POST",
                "path": "/api/reactions",
                "auth": "bearer:reaction:write",
                "purpose": "在用户确认后把同一份已校验草稿保存到该用户的反应库",
                "required_header": "Idempotency-Key；同一次保存的重试复用，其他草稿不得复用",
            },
        ],
        "payload_hints": {
            "required": ["visibility", "participants", "source_type"],
            "participant_required": ["role", "smiles"],
            "participant_roles": ["REACTANT", "REAGENT", "CATALYST", "SOLVENT", "PRODUCT"],
            "minimum_structure": "至少一个 REACTANT 和一个 PRODUCT",
            "visibility": "未得到公开确认时使用 private；public 必须由用户明确确认",
            "paired_fields": [
                "amount_value + amount_unit",
                "concentration_value + concentration_unit",
                "temperature_value + temperature_unit",
                "duration_value + duration_unit",
                "pressure_value + pressure_unit",
            ],
            "source_types": {
                "self": "用户本人实验",
                "doi": "同时提供 doi",
                "patent": "同时提供 patent",
                "url": "同时提供 source_url",
                "database": "同时提供 source_citation",
                "other": "同时提供 source_citation",
            },
        },
        "workflow": [
            "读取用户提供的网页、文档、图片或文本并保留来源证据",
            "只提取明确事实；结构有歧义或必要字段缺失时先询问用户",
            "形成结构化草稿；用户未决定公开时设置 visibility=private",
            "向用户展示参与物、条件、来源和可见范围并取得保存确认",
            "使用同一份 payload 调用 POST /api/reactions/validate",
            "校验通过后，携带唯一 Idempotency-Key 调用 POST /api/reactions",
            "返回 HRID、页面地址、可见范围和 created_chemical_ids",
        ],
        "rules": [
            "不得编造 SMILES、来源、条件、用量、收率或实验过程；未知可选字段应省略。",
            "查到多个可能结构时让用户选择，不按结果顺序猜测。",
            "同一角色和标准结构不得拆成重复参与物；使用 occurrence_count。",
            "校验不会保存；只有 POST /api/reactions 会创建记录。",
            "API Token 只开放查询、校验和新建；编辑、可见性调整与删除在网页完成。",
            "未收到成功响应不得声称已保存。",
        ],
        "errors": {
            "400_or_422": "按 detail 修正字段或结构后重新校验，不补猜缺失事实",
            "401": "停止操作；Token 无效、已过期或已撤销，请用户重新授权",
            "403": "停止操作；当前授权不允许该动作，不尝试其他接口绕过",
            "404": "核对稳定标识符，不推测相邻 ID",
            "409": "按 detail 处理重复参与物或幂等冲突",
            "429": "遵循 Retry-After，降低请求频率",
        },
        "rate_limits": {
            "queries_per_minute": settings.api_query_limit_per_minute,
            "structure_queries_per_minute": settings.api_structure_limit_per_minute,
            "svg_renders_per_minute": settings.api_render_limit_per_minute,
            "reaction_writes_per_minute": settings.api_reaction_write_limit_per_minute,
            "reaction_writes_per_day": settings.api_reaction_write_limit_per_day,
            "stoichiometry_per_minute": settings.api_stoich_limit_per_minute,
            "skill_writes_per_hour": settings.api_skill_write_limit_per_hour,
        },
    }
