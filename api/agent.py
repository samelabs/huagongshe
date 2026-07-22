"""Small self-describing connection surface for user-authorized AI clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from .config import settings
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
):
    """Return the complete, bounded operation guide; a Bearer token also confirms its owner."""
    bearer_supplied = bool(authorization and authorization.lower().startswith("bearer "))
    if bearer_supplied and actor is None:
        raise HTTPException(401, "API Token 无效、已过期或已撤销")

    agent = actor if actor and actor.auth_kind == "agent" else None
    origin = settings.public_base_url.rstrip("/")
    api_base = f"{origin}/api"
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
                else "创建 AI 授权后，以 Authorization: Bearer <Token> 再次读取本入口以确认连接。"
            ),
        },
        "authentication": {
            "type": "bearer",
            "header": "Authorization: Bearer <用户创建的 API Token>",
            "scopes": list(agent.scopes) if agent else ["read", "reaction:write"],
            "token_handling": "Token 仅发送给 huagongshe.com，不写入公开提示词、代码、文件或日志。",
        },
        "discovery": {
            "openapi_url": f"{api_base}/openapi.json",
            "help_url": f"{origin}/guide",
            "optional_skill_url": f"{origin}/skills/huagongshe-reaction-publisher/SKILL.md",
            "instruction": "先从 operations 选择操作；只有需要精确请求或响应结构时才读取 OpenAPI。",
        },
        "operations": [
            {
                "id": "search_chemistry_data",
                "method": "GET",
                "path": "/api/search",
                "auth": "public_or_bearer",
                "purpose": "按名称、CAS、HCID、CID、InChIKey、DOI、SMILES 或结构查询化合物和反应",
                "input": "q 必填；mode 为 exact、substructure 或 similarity；page_size 最大 50",
            },
            {
                "id": "get_chemical",
                "method": "GET",
                "path": "/api/chemicals/{chemical_id}",
                "auth": "public_or_bearer",
                "purpose": "读取一个 HCID 的结构、标识符、性质和关联反应概况",
            },
            {
                "id": "get_reaction",
                "method": "GET",
                "path": "/api/reactions/{reaction_id}",
                "auth": "public_or_bearer",
                "purpose": "读取一个 HRID；Token 所属用户也可读取自己的私有记录",
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
                "id": "validate_reaction",
                "method": "POST",
                "path": "/api/reactions/validate",
                "auth": "bearer:reaction:write",
                "purpose": "校验草稿并返回 RDKit 标准化后的 reaction SMILES 和参与物",
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
            "reaction_writes_per_minute": settings.api_reaction_write_limit_per_minute,
            "reaction_writes_per_day": settings.api_reaction_write_limit_per_day,
        },
    }
