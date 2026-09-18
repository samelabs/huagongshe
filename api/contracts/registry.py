"""Governance registry (G1 final) — G1A 冻结结论的机械落实。

事实源(证据优先级: runtime 代码 > 测试 > 消费者 > 公开契约 > 注释):
- WEB: web/lib/api.ts + components 全量调用面
- AGENT_HTTP: api/agent.py(agent-guide 15 operations)
- AGENT_MCP: api/mcp_server.py @server.tool(14; list_skills/get_skill 的
  public/slug 分支匿名可用 —— 逐行核实, 不是"全 tool 需登录")
- DISCOVERY: web/public/llms.txt + sitemap 语义
- WorkAPI scope: api/workapi.py ROUTE_SCOPE(pubchem/cas; identity 沿用 pubchem)

Compatibility 登记依据(逐 scenario, 与 Consumer 无推导关系):
- agent-guide 15 operations + guide 自身 → STABLE_EXTERNAL
- 14 MCP tools → STABLE_EXTERNAL
- WorkAPI(Web/Admin/OPS/内部面) → NONE(trusted internal protocol,
  不冒充 public compatibility)
- DISCOVERY 场景不因 consumer 自动稳定: PNG/datasets/sitemap 无稳定兼容
  承诺证据(llms.txt 是弱承诺简介) → Compatibility.NONE
"""

from __future__ import annotations

from .model import (
    AuthPolicy as A,
    Compatibility as X,
    Contract,
    Consumer as C,
    Effect as E,
    Entrypoint as I,
    Family,
    KernelLink as K,
    Scenario as S,
    Transport as T,
)


def _fams() -> list[Family]:
    return [
        # ------------------------------------------------------------------
        # search(G1A 冻结: SHARE_SERVICE 单 service + 三独立 scenario policy)
        # ------------------------------------------------------------------
        Family("search", E.READ, scenarios=(
            S("exact", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/search", "mode=exact"),
                I(T.MCP, "search_chemistry_data", "mode=exact"),
            ), contract=Contract(
                frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                X.STABLE_EXTERNAL, "search_chemistry_data"),
            ),
            S("substructure", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/search", "mode=substructure"),
                I(T.MCP, "search_chemistry_data", "mode=substructure"),
            ), contract=Contract(
                frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                X.STABLE_EXTERNAL, "search_chemistry_data"),
            ),
            S("similarity", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/search", "mode=similarity"),
                I(T.MCP, "search_chemistry_data", "mode=similarity"),
            ), contract=Contract(
                frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                X.STABLE_EXTERNAL, "search_chemistry_data"),
            ),
        ), kernels=(
            K("search.service.unified", ("search/exact", "search/substructure",
                                         "search/similarity")),
        )),

        # ------------------------------------------------------------------
        # chemicals 读取
        # ------------------------------------------------------------------
        Family("chemical.read", E.READ, scenarios=(
            S("detail", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/chemicals/{chemical_id}"),
                I(T.MCP, "get_chemical")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "get_chemical")),
            S("externals", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/chemicals/{chemical_id}/externals"),
                I(T.MCP, "get_chemical_externals")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "get_chemical_externals")),
            S("reactions", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/chemicals/{chemical_id}/reactions"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("synonyms", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/chemicals/{chemical_id}/synonyms"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),

        # ------------------------------------------------------------------
        # molecule rendering(G1A 冻结: SHARE_KERNEL, SVG/PNG 独立 scenario+contract)
        # ------------------------------------------------------------------
        Family("molecule.rendering", E.READ, scenarios=(
            S("svg", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/mol/{chemical_id}/svg"),
                I(T.MCP, "render_molecule_svg")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP, C.DISCOVERY}),
                                X.STABLE_EXTERNAL, "render_molecule_svg")),
            S("png", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/mol/{chemical_id}/png"),),
              # DISCOVERY=llms.txt 未列 PNG; og:image 用途, 无稳定兼容承诺证据
              contract=Contract(frozenset({C.WEB, C.DISCOVERY}), X.NONE),
              note="og:image 用途; guide 未收录, 契约独立于 svg(G1A 冻结)"),
        ), kernels=(
            K("render.kernel.molecule", ("molecule.rendering/svg", "molecule.rendering/png")),
        )),

        # ------------------------------------------------------------------
        # reaction rendering(G1A: visibility-aware, cache policy 独立于 molecule)
        # ------------------------------------------------------------------
        Family("reaction.rendering", E.READ, scenarios=(
            S("svg", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/reactions/{reaction_id}/svg"),
                I(T.MCP, "render_reaction_svg")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP, C.DISCOVERY}),
                                X.STABLE_EXTERNAL, "render_reaction_svg"),
              note="visibility-aware 缓存(300s/private); MCP 侧查 SQL 为内联复制(D008)"),
        ), kernels=(
            K("render.kernel.reaction", ("reaction.rendering/svg",)),
        )),

        # ------------------------------------------------------------------
        # reactions 内容
        # ------------------------------------------------------------------
        Family("reaction.read", E.READ, scenarios=(
            S("detail", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/reactions/{reaction_id}"),
                I(T.MCP, "get_reaction")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "get_reaction")),
        )),
        Family("reaction.write", E.WRITE, scenarios=(
            S("validate", A.ACTOR, required_scope=("reaction:write",), entrypoints=(
                I(T.HTTP, "POST /api/reactions/validate"),
                I(T.MCP, "validate_reaction")),
              contract=Contract(frozenset({C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "validate_reaction")),
            S("create", A.ACTOR, required_scope=("reaction:write",), entrypoints=(
                I(T.HTTP, "POST /api/reactions"),
                I(T.MCP, "create_reaction")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "create_reaction"),
              note="同事务: Web session 与 AI Key 同一 create-reaction 事务服务; "
                   "MCP 直调 handler(request=None, 参数未使用), 同 enforce+幂等"),
            S("list_own", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/me/reactions"),
                I(T.MCP, "list_my_reactions")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "list_my_reactions")),
            S("update", A.ACTOR, entrypoints=(
                I(T.HTTP, "PUT /api/reactions/{reaction_id}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="E3: 行锁/owner 检查/事务在 application service"
                   "(services.reactions.update_reaction); agent 403 由 service "
                   "中性错误 + adapter 映射; D001 挂账"),
            S("delete", A.ACTOR, entrypoints=(
                I(T.HTTP, "DELETE /api/reactions/{reaction_id}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="E3: 行锁/系统导入与 owner 检查/事务在 application service"
                   "(services.reactions.delete_reaction); agent 403 由 service "
                   "中性错误 + adapter 映射"),
        ), kernels=(
            K("reaction.tx.create", ("reaction.write/create",)),
        )),

        # ------------------------------------------------------------------
        # skills(G1A 冻结: 同一 query/service, 契约如实声明;
        # MCP list_skills public 分支匿名可用 —— 与 HTTP 同语义)
        # ------------------------------------------------------------------
        Family("skill.read", E.READ, scenarios=(
            S("list_public", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/skills", "scope=public"),
                I(T.MCP, "list_skills", "scope=public")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "list_skills")),
            S("list_mine", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/skills", "scope=mine"),
                I(T.MCP, "list_skills", "scope=mine")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "list_skills"),
              note="mine 分支需已解析 actor; HTTP/MCP 同语义(_require_login 无 scope 检查)"),
            S("get", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/skills/{skill_id}"),
                I(T.MCP, "get_skill")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "get_skill"),
              note="private 仅 owner 可读(endpoint 内分支); MCP slug 解析为"
                   " adapter 逻辑(fail-closed 契约测试锁定)"),
            S("archive", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/skills/{skill_id}/archive"),),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "download_skill_archive"),
              note="E4: skill_files 查询 + 目录/文件缺失判定 + zip 组装在 application "
                   "service(build_skill_archive); adapter 只余 access 404 桥 + "
                   "Response 构造"),
            S("read_file", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/skills/{skill_id}/content/{file_path:path}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="E4: manifest 行读取 + is_text 判定 + FS 读取在 application "
                   "service(read_skill_file); 404 原文不变"),
            S("categories", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/skills/categories"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        ), kernels=(
            K("skill.query.list", ("skill.read/list_public", "skill.read/list_mine")),
        )),
        Family("skill.write", E.WRITE, scenarios=(
            S("validate", A.ACTOR, required_scope=("skill:write",), entrypoints=(
                I(T.HTTP, "POST /api/skills/validate"),
                I(T.MCP, "validate_skill")),
              contract=Contract(frozenset({C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "validate_skill")),
            S("create", A.ACTOR, required_scope=("skill:write",), entrypoints=(
                I(T.HTTP, "POST /api/skills"),
                I(T.MCP, "create_skill")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "create_skill"),
              note="同事务; Web session(SkillsPanel apiPost)与 AI Key 同一 create-skill 服务"),
            S("update", A.ACTOR, entrypoints=(
                I(T.HTTP, "PATCH /api/skills/{skill_id}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="E4: owner 检查/agent 403 在 endpoint; validation+DB mutation+"
                   "commit+readback 在 application service(update_skill_metadata)"),
            S("delete", A.ACTOR, entrypoints=(
                I(T.HTTP, "DELETE /api/skills/{skill_id}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="E4: owner 检查/agent 403 在 endpoint; 行锁+DB 删除+FS staging+"
                   "补偿在 application service(delete_skill_lifecycle, 与 admin "
                   "delete 共用同一 owner)"),
        ), kernels=(
            K("skill.tx.create", ("skill.write/create",)),
        )),

        # ------------------------------------------------------------------
        # stoichiometry(MCP actor 可选透传: 匿名=anon 桶, 登录=u{id} 桶)
        # ------------------------------------------------------------------
        Family("stoichiometry", E.READ, scenarios=(
            S("calculate", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "POST /api/stoichiometry/scale"),
                I(T.MCP, "calculate_stoichiometry")),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP, C.AGENT_MCP}),
                                X.STABLE_EXTERNAL, "calculate_stoichiometry")),
        )),

        # ------------------------------------------------------------------
        # account / auth / profile / token / avatar(G1A: 文件粘合, 职责分域登记)
        # ------------------------------------------------------------------
        Family("account.auth", E.WRITE, scenarios=(
            S("register", A.ANONYMOUS, entrypoints=(
                I(T.HTTP, "POST /api/auth/register"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("login", A.ANONYMOUS, entrypoints=(
                I(T.HTTP, "POST /api/auth/login"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("logout", A.ANONYMOUS, entrypoints=(
                I(T.HTTP, "POST /api/auth/logout"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("check_username", A.ANONYMOUS, entrypoints=(
                I(T.HTTP, "GET /api/auth/check-username"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),
        Family("account.identity", E.READ, scenarios=(
            S("me", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/me"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("dashboard", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/me/dashboard"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),
        Family("account.profile", E.WRITE, scenarios=(
            S("update", A.SESSION, entrypoints=(
                I(T.HTTP, "PATCH /api/users/me"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("password", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/users/me/password"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),
        Family("account.avatar", E.WRITE, scenarios=(
            S("upload", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/users/me/avatar"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("delete", A.SESSION, entrypoints=(
                I(T.HTTP, "DELETE /api/users/me/avatar"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="独立 media pipeline(尺寸变体), G1A: 独立演进"),
        )),
        Family("account.token", E.PRIVILEGED, scenarios=(
            S("list", A.SESSION, entrypoints=(
                I(T.HTTP, "GET /api/users/me/tokens"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("create", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/users/me/tokens"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("revoke", A.SESSION, entrypoints=(
                I(T.HTTP, "DELETE /api/users/me/tokens/{token_id}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),

        # ------------------------------------------------------------------
        # social / public profile(G1A: follow Web-only 合理, MCP 不新增)
        # ------------------------------------------------------------------
        Family("social.follow", E.WRITE, scenarios=(
            S("follow_user", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/users/{username}/follow"),
                I(T.HTTP, "DELETE /api/users/{username}/follow")),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="G1A 冻结: 无 MCP 面, 禁止因技术可行规划(P4)"),
            S("follow_reaction", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/reactions/{reaction_id}/follow"),
                I(T.HTTP, "DELETE /api/reactions/{reaction_id}/follow")),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("follow_chemical", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/chemicals/{chemical_id}/follow"),
                I(T.HTTP, "DELETE /api/chemicals/{chemical_id}/follow")),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),
        Family("social.read", E.READ, scenarios=(
            S("follows_chemicals", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/me/follows/chemicals"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("follows_reactions", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/me/follows/reactions"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("notifications", A.ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/me/notifications"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("notifications_read", A.SESSION, entrypoints=(
                I(T.HTTP, "POST /api/users/me/notifications/read"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),
        Family("user.public", E.READ, scenarios=(
            S("profile", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/{username}"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("followers", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/{username}/followers"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("following", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/{username}/following"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
            S("reactions", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/users/{username}/reactions"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),

        # ------------------------------------------------------------------
        # enrichment / config / discovery / guide / ops
        # ------------------------------------------------------------------
        Family("enrichment", E.READ, scenarios=(
            S("details_refresh", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/chemicals/{chemical_id}/details"),),
              contract=Contract(frozenset({C.WEB}), X.NONE),
              note="D007: 前端零消费疑似死面(P2 裁定); 场景=详情读+陈旧回补入队"),
        )),
        Family("config", E.READ, scenarios=(
            S("public_read", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/config"),),
              contract=Contract(frozenset({C.WEB}), X.NONE)),
        )),
        Family("dataset", E.READ, scenarios=(
            S("list", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/datasets"),),
              # llms.txt 为弱承诺简介, 无稳定兼容承诺 → NONE(仍是 DISCOVERY consumer)
              contract=Contract(frozenset({C.DISCOVERY}), X.NONE),
              note="P3 裁定升入 guide 与否"),
        )),
        Family("discovery.sitemap", E.READ, scenarios=(
            S("reactions", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/sitemap/reactions"),),
              contract=Contract(frozenset({C.DISCOVERY}), X.NONE),
              note="sitemap 生成语义的公开 keyset 端点, 非产品功能面"),
        )),
        Family("guide", E.READ, scenarios=(
            S("agent", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/agent-guide"),),
              contract=Contract(frozenset({C.WEB, C.AGENT_HTTP}),
                                X.STABLE_EXTERNAL, "get_agent_connection_guide")),
        )),
        Family("ops.health", E.READ, scenarios=(
            S("health", A.PUBLIC_OR_ACTOR, entrypoints=(
                I(T.HTTP, "GET /api/health"),),
              contract=Contract(frozenset({C.OPS}), X.NONE),
              note="handler 不读身份; registry 从宽登记(与 ANONYMOUS 运行时等价)"),
        )),

        # ------------------------------------------------------------------
        # admin(G1A: 九块独立 scenario, adapter 聚合短期接受)
        # ------------------------------------------------------------------
        Family("admin.worker", E.PRIVILEGED, scenarios=(
            S("manage", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/workers"),
                I(T.HTTP, "POST /api/admin/workers"),
                I(T.HTTP, "PATCH /api/admin/workers/{worker_id}")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),
        Family("admin.user_governance", E.PRIVILEGED, scenarios=(
            S("manage", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/users"),
                I(T.HTTP, "PATCH /api/admin/users/{user_id}/role"),
                I(T.HTTP, "PATCH /api/admin/users/{user_id}/status")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),
        Family("admin.reaction_moderation", E.PRIVILEGED, scenarios=(
            S("moderate", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/reactions"),
                I(T.HTTP, "PATCH /api/admin/reactions/{reaction_id}/moderation")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),
        Family("admin.skill_moderation", E.PRIVILEGED, scenarios=(
            S("moderate", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/skills"),
                I(T.HTTP, "DELETE /api/admin/skills/{skill_id}"),
                I(T.HTTP, "PATCH /api/admin/skills/{skill_id}/visibility")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE),
              note="E4: DELETE 与 user delete 共用 application service "
                   "delete_skill_lifecycle; 差异仅在授权 dep 与响应 shape"),
        )),
        Family("admin.skill_category", E.PRIVILEGED, scenarios=(
            S("manage", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/skill-categories"),
                I(T.HTTP, "POST /api/admin/skill-categories"),
                I(T.HTTP, "PATCH /api/admin/skill-categories/{category_id}")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),
        Family("admin.config", E.PRIVILEGED, scenarios=(
            S("manage", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/config"),
                I(T.HTTP, "PUT /api/admin/config/{namespace}/{key}")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),
        Family("admin.dashboard", E.PRIVILEGED, scenarios=(
            S("read", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/dashboard"),),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),
        Family("admin.pipeline", E.PRIVILEGED, scenarios=(
            S("read", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "GET /api/admin/pipeline"),
                I(T.HTTP, "GET /api/admin/pipeline/governance"),
                I(T.HTTP, "GET /api/admin/pipeline/governance/drilldown/{key}")),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
            S("revive", A.ADMIN_SESSION, entrypoints=(
                I(T.HTTP, "POST /api/admin/pipeline/{chain}/errors/revive"),),
              contract=Contract(frozenset({C.ADMIN}), X.NONE)),
        )),

        # ------------------------------------------------------------------
        # WorkAPI(G1A: HMAC protocol 共享, queue domain 独立;
        # trusted internal protocol → Compatibility.NONE;
        # identity 沿用 pubchem scope, P1 维持现状)
        # ------------------------------------------------------------------
        Family("worker.pubchem_jobs", E.WRITE, scenarios=(
            S("lease", A.WORKER_HMAC, required_scope=("pubchem",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/jobs/lease"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
            S("complete", A.WORKER_HMAC, required_scope=("pubchem",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/jobs/complete"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
            S("error", A.WORKER_HMAC, required_scope=("pubchem",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/jobs/error"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
        )),
        Family("worker.cas_jobs", E.WRITE, scenarios=(
            S("lease", A.WORKER_HMAC, required_scope=("cas",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/cas/jobs/lease"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
            S("heartbeat", A.WORKER_HMAC, required_scope=("cas",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/cas/jobs/heartbeat"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
            S("complete", A.WORKER_HMAC, required_scope=("cas",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/cas/jobs/complete"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
            S("error", A.WORKER_HMAC, required_scope=("cas",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/cas/jobs/error"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
        )),
        Family("worker.identity_jobs", E.WRITE, scenarios=(
            S("lease", A.WORKER_HMAC, required_scope=("pubchem",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/identity/jobs/lease"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE),
              note="identity 沿用 pubchem scope(0912 P0-1 裁定; P1 维持)"),
            S("complete", A.WORKER_HMAC, required_scope=("pubchem",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/identity/jobs/complete"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
            S("error", A.WORKER_HMAC, required_scope=("pubchem",), entrypoints=(
                I(T.WORKAPI, "POST /workapi/v1/identity/jobs/error"),),
              contract=Contract(frozenset({C.WORKER}), X.NONE)),
        )),
    ]


FAMILIES: tuple[Family, ...] = tuple(_fams())
