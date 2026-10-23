"""MCP 工具参数契约常量与渲染资源闸门参数（注册面与实现共用单一来源）。"""
# ---------------------------------------------------------------------------
# MCP 工具参数契约单一来源 —— tools/list 的 schema 约束与函数体内的
# 运行时校验取同一组常量(漂移即测试失败)。schema 收紧后越界值在入参校验即
# 报错(原先静默 clamp), clamp 语句保留为双保险。
# ---------------------------------------------------------------------------
QUERY_MAX_LENGTH = 4000
SEARCH_PAGE_MAX = 20
SEARCH_PAGE_SIZE_DEFAULT = 30
SEARCH_PAGE_SIZE_MAX = 100
THRESHOLD_MIN = 0.4
THRESHOLD_MAX = 1.0
ID_MAX = 2_147_483_647
RENDER_SIZE_MIN = 50
RENDER_SIZE_MAX = 800
SMILES_MAX_LENGTH = 512
SKILL_QUERY_MAX_LENGTH = 120
SKILL_CATEGORY_MAX_LENGTH = 40
LIST_PAGE_MAX = 500
MY_REACTIONS_PAGE_SIZE_DEFAULT = 20
MY_REACTIONS_PAGE_SIZE_MAX = 50
IDEMPOTENCY_KEY_MAX_LENGTH = 200

# ---------------------------------------------------------------------------
# MCP 渲染资源闸门(B5)
# ---------------------------------------------------------------------------
# 两个 render tool 共用同一资源池: render_molecule_svg / render_reaction_svg。
# RDKit 渲染是 CPU-bound(外部直传 SMILES 可占分钟级), 复用与结构检索同一组
# 原语: enforce(fixed-window 限频) + acquire_lease/release_lease(in-flight 租约)。
# - 已认证 actor 120 次/分钟, 匿名按来源 IP 各 120 次/分钟(x-real-ip)
# - 已认证 actor in-flight ≤ 2(匿名不额外持 actor 租约)
# - 全局 in-flight ≤ 4
# - Redis acquire 失败 fail-closed(503 → ToolError), 不放行
# - 闸门必须在 RDKit to_thread 之前, finally 必释放
MCP_RENDER_BUCKET = "mcp-render"
MCP_RENDER_RATE_LIMIT = 120
MCP_RENDER_ACTOR_INFLIGHT = 2
MCP_RENDER_GLOBAL_INFLIGHT = 4
