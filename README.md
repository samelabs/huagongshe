# 化工社

化工社是开放、非商业化的化学数据与反应发布平台，线上域名为 `https://huagongshe.com`。

## 产品主线

- `chemistry.chemicals` 是全局化合物身份底座。PubChem、DSSTox 和 RDKit/ORD 只作为来源和补全能力，不形成并行产品库。
- `chemistry.reactions` 是唯一反应内容实体。系统导入反应和用户发布反应共享 HRID、RDKit 表达与查询链路。
- `chemistry.reaction_chemicals` 是 HRID 与 HCID 的唯一参与关系。
- 用户发布反应时直接写入上述实体，不经过人工科学审核，不存在待审核缓存层。
- 用户拥有自己发布的反应，可以编辑、设为公开或私有，也可以直接删除；关联 chemicals 不随反应删除。

## 用户能力

- 注册、登录、公开资料与压缩头像；
- 公开和私有反应仓库；
- 发布、维护和删除自己的反应；
- 关注用户、化合物和公开反应；
- 关注用户发布公开反应时接收站内动态；化合物和反应关注只形成个人列表，不触发通知；
- 创建与账号绑定的 API Token，为 AI 或其他客户端授权。

平台管理只处理账号状态和用户反应可见度，不判断反应是否科学正确。项目不提供开放评论、求助、私信或审核队列。

## 反应发布事务

网页和 AI Agent 共用同一个反应字段模型和反应写入逻辑：

1. 校验参与物、条件、来源和可见性；
2. 使用 RDKit 标准化每个 SMILES 并验证 reaction SMILES；
3. 匹配现有 HCID，缺失时创建 chemical 及 mol、指纹、InChIKey、分子式和质量；
4. 创建 HRID；
5. 写入 `reaction_chemicals`；
6. 在同一数据库事务中提交，任一步失败全部回滚。

用户反应至少包含反应物、产物和来源类型。未知过程、条件或收率可以留空，禁止为了字段完整而猜测。

## API 边界

- `/api/*`：网站与用户 AI Agent 共用的查询和用户能力。
- `/api/agent-guide`：面向 AI Agent 的字段语义、行为规则和调用顺序。
- `/api/openapi.json`：稳定的结构化契约。
- `/guide`：面向用户的网页发布、AI 对话提示词与 Skill 使用指南。
- `/skills/huagongshe-reaction-publisher/SKILL.md`：可直接交给 AI 的反应整理与发布 Skill。
- `/workapi/*`：只服务受信任 PubChem worker，与用户 Agent 完全无关。

网站使用安全 HttpOnly Cookie。AI Agent 使用用户创建的 API Token（Bearer Token）；数据库只保存 Token 摘要。AI 正式提交反应必须提供 `Idempotency-Key`，网络重试不会重复创建 HRID。查询和写入均由 Redis 限速。

## 化合物事实规则

- `chemistry.chemicals.id` 是稳定 HCID；PubChem CID 只标识 PubChem 来源子集。
- `smiles` 是 RDKit 标准表达，也是跨来源结构对齐基础。
- DSSTox 数据只能在标准结构或完整 InChIKey 验证后挂载，CAS 不能单独确认结构。
- PubChem PUG REST 用于 CID、结构和计算属性；PUG View 用于带来源的扩展信息。
- PubChem worker 可以补全名称、分子式、质量、InChIKey 和同义词，但不能修改 HCID、CID 或标准 SMILES。

## 检索

- 精确 SMILES 使用部分 B-tree；
- 子结构使用 RDKit mol GiST；
- 相似结构使用 Morgan bit-vector GiST KNN；
- 外部数组标识使用 GIN，名称使用独立 trigram GIN；
- 反应检索使用 RDKit reaction GiST 和 `(chemical_id,reaction_id)` 关系索引。

子结构查询不得按 HCID 在数据库中预排序，否则 PostgreSQL 会放弃 RDKit GiST。API 只对有限结果在内存中排序。

## 代码边界

- `api/routes.py`：公开化学查询；
- `api/reactions.py`：网页与 Agent 共用的唯一反应写入能力；
- `api/users.py`、`api/security.py`：用户、头像、会话和 API Token；
- `api/social.py`：三类关注与通知；
- `api/admin.py`：账号和可见度治理；
- `api/workapi.py`：PubChem worker 维护接口；
- `web/`：Next.js 用户界面；
- `migrations/`：可审计数据库迁移；
- `archive/`：已经结束的一次性数据迁移程序，不参与线上运行。

## 线上运行

- `huagongshe-api.service`：`127.0.0.1:8000`
- `huagongshe-web.service`：`127.0.0.1:3001`
- `huagongshe-pubchem-worker.service`：本机 PubChem 补全 worker
- Nginx：HTTPS、同域 `/api`、独立 `/workapi` 与版本化头像静态文件

生产源码固定在 `/var/www/huagongshe`。前端只运行
`web/.next/standalone`，服务器不保留用于开发构建的完整 `web/node_modules`；
构建在开发机完成后发布 standalone 产物。Python 依赖固定在项目根目录的 `venv`。

GitHub `samelabs/huagongshe` 是版本中心，本地开发目录与生产目录都跟踪 `main`，
禁止在服务器保留未提交源码改动。

```bash
systemctl status huagongshe-api huagongshe-web huagongshe-pubchem-worker nginx postgresql redis-server
curl -fsS https://huagongshe.com/api/health
```

数据库凭据、用户 Token 和 worker Token 不写入 Git。
