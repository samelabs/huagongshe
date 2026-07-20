# 化工社

化工社是开放、非商业化的化学数据项目，以化合物和反应为两个核心对象。线上站点为 `https://huagongshe.com`。

## 数据边界

- `chemistry.chemicals`：化合物身份、标准结构、基础属性与外部标识。
- `chemistry.reactions`：反应身份与可检索的反应表达。
- `chemistry.reaction_chemicals`：反应与化合物的角色关系。
- `community.*`：用户、会话、数据提交和反应求助。
- `ord.*`：ORD 原始反应事实与来源上下文，不承担化工社自主身份。
- `ingest.*`：PubChem、DSSTox、RDKit/ORD 迁移审计和一次性导入数据，不进入线上查询路径。
- `maintenance.*`：持久任务、worker 身份和维护审计，不进入公共查询模型。

PubChem、DSSTox 和 ORD 是数据来源；RDKit 是解析、标准化和检索能力。它们都不形成与 `chemistry` 并列的产品数据主线。

## 化合物事实规则

- `chemistry.chemicals.id` 是项目稳定的 `chemical_id`；PubChem CID 只标识 PubChem 来源子集。
- `smiles` 是 RDKit 标准化后的结构表达，也是 chemicals 与 ORD 共存、跨来源对齐的基础。
- DSSTox 数据只能在标准化 SMILES 或完整 InChIKey 验证后挂载，CAS 不能单独确认结构。
- PubChem `CID-Identifiers` 是缺少逐值来源上下文的第三方关联集合，不得直接作为已核实外部标识写入。
- CAS、EC、UNII、ChEMBL、ChEBI、Nikkaji 等允许真实多值；每个值必须保留来源证据并通过实体或结构粒度核验。
- PubChem PUG REST 用于 CID、结构和计算属性；PUG View 用于带来源的物性、安全、毒性和外部标识注释。
- 扩展信息按需写入 `chemistry.chemical_details`，禁止为 1.24 亿条 chemicals 预建空行或保存完整 PUG View 原文。

## API 边界

- `/api/*`：面向用户和前端的查询、社区提交及查询触发的按需补全状态。
- `/workapi/*`：只接受受信任 worker 的签名 POST；不提供公共数据查询。
- worker 不持有数据库凭据。它通过 `/workapi` 领取租约、报告状态并提交 PubChem 结果；最终标准化、校验和事务写入由 API 完成。
- PubChem 访问节流属于 worker 自身能力，不由 `/workapi` 提供限速或流量协调服务。

## 社区数据闭环

1. 用户注册并登录；密码在服务端进行强度和二次输入一致性校验，会话使用安全的 HttpOnly Cookie。
2. 化合物提交先经 RDKit/CAS 格式校验和现有数据匹配；反应提交按参与物角色、过程、条件、收率和来源结构化保存。
3. `editor` 或 `admin` 在 `/admin` 审核。拒绝必须说明原因；接受会在一个数据库事务内写入或更新 `chemistry.chemicals`、`chemistry.reactions` 和 `chemistry.reaction_chemicals`。
4. 用户在 `/submit` 查看审核状态；接受后的对象可直接进入化合物或反应详情页。

## 检索与反应表达

- 精确 SMILES 使用部分 B-tree；子结构使用 `chemicals_mol_gist_idx`；相似结构使用 Morgan bit-vector GiST KNN。
- 子结构 SQL 不得按 `chemical_id` 预排序。该排序会让 PostgreSQL 放弃 RDKit GiST，改为扫描主键后逐行判断；API 只对有限结果做内存排序。
- CAS 等数组标识使用 GIN，名称使用独立 trigram GIN，反应与化合物关系使用 `(chemical_id,reaction_id)` 覆盖索引。
- 当前 2,428,291 条反应中，2,428,170 条已有反应 SMILES 和 RDKit reaction。剩余 121 条缺少反应物或生成物，按原因记录在 `ingest.reaction_rdkit_failures`，页面不得尝试渲染不存在的方程式。

审核权限不随注册自动授予。服务器管理员核实账号后执行：

```sql
UPDATE community.users SET role='editor' WHERE lower(email)=lower('reviewer@example.com');
```

## 代码边界

- `api/`：FastAPI 公共 `/api` 与维护 `/workapi`，两个路由域严格分离。
- `worker/`：无数据库权限、通过维护 API 闭环运行的 PubChem worker。
- `web/`：Next.js 简洁查询与社区入口。
- `migrations/`：可审计的数据库结构迁移。

## 线上运行

- `huagongshe-api.service`：`127.0.0.1:8000`
- `huagongshe-web.service`：`127.0.0.1:3001`
- Nginx：HTTPS、同域 `/api/*` 代理与 `www` 到主域跳转。
- Nginx：`/workapi/*` 独立限流并代理到维护 API；所有请求仍强制 HTTPS。

```bash
systemctl status huagongshe-api huagongshe-web nginx postgresql redis-server
curl -fsS https://huagongshe.com/api/health
```

API 连接信息由服务器上的 `/etc/huagongshe/api.env` 提供，不写入 Git。

## PubChem 按需补全

PubChem 结果通过 CID 与标准结构双重校验后，同步维护 `chemistry.chemicals` 的名称、分子式、质量、InChIKey 和完整活动别名；CID 与 SMILES 不由 worker 改写。完整别名保存在主表中，公共详情只返回有限预览，分页接口按需读取全量，避免拖大搜索与列表响应。`chemistry.chemical_details` 是稀疏的一对一扩展表：只有实际被请求的 chemical 才产生行，且各信息分区分别记录抓取时间。`maintenance.pubchem_jobs` 是可恢复的租约队列；worker 崩溃或失联后任务会重试，超过次数进入 `dead`，不会无限循环。

worker 通过 `python -m worker.issue_token WORKER_ID` 生成一次性凭据。数据库只保存令牌摘要；worker 环境只需要本机 `/workapi` 地址、worker ID 和令牌，不需要数据库连接。生产服务使用 `deploy/huagongshe-pubchem-worker.service`。

PUG View 外部标识先写入 `identifier_evidence`，并保留 CAS、Related CAS、Deprecated CAS 等语义和逐值来源。它不会自动修改 `chemicals.cas_numbers` 等核心索引字段；核心字段的晋升必须经过来源与结构粒度规则。
