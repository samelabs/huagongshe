# 化工社

化工社是开放、非商业化的化学数据项目，以化合物和反应为两个核心对象。线上站点为 `https://huagongshe.com`。

## 数据边界

- `chemistry.chemicals`：化合物身份、标准结构、基础属性与外部标识。
- `chemistry.reactions`：反应身份与可检索的反应表达。
- `chemistry.reaction_chemicals`：反应与化合物的角色关系。
- `community.*`：用户、会话、数据提交和反应求助。
- `ord.*`：ORD 原始反应事实与来源上下文，不承担化工社自主身份。
- `ingest.*`：PubChem、DSSTox、RDKit/ORD 迁移审计和一次性导入数据，不进入线上查询路径。

PubChem、DSSTox 和 ORD 是数据来源；RDKit 是解析、标准化和检索能力。它们都不形成与 `chemistry` 并列的产品数据主线。

## 社区数据闭环

1. 用户注册并登录；密码在服务端进行强度和二次输入一致性校验，会话使用安全的 HttpOnly Cookie。
2. 化合物提交先经 RDKit/CAS 格式校验和现有数据匹配；反应提交按参与物角色、过程、条件、收率和来源结构化保存。
3. `editor` 或 `admin` 在 `/admin` 审核。拒绝必须说明原因；接受会在一个数据库事务内写入或更新 `chemistry.chemicals`、`chemistry.reactions` 和 `chemistry.reaction_chemicals`。
4. 用户在 `/submit` 查看审核状态；接受后的对象可直接进入化合物或反应详情页。

审核权限不随注册自动授予。服务器管理员核实账号后执行：

```sql
UPDATE community.users SET role='editor' WHERE lower(email)=lower('reviewer@example.com');
```

## 代码边界

- `api/`：FastAPI 同域 API。
- `web/`：Next.js 简洁查询与社区入口。
- `migrations/`：可审计的数据库结构迁移。

## 线上运行

- `huagongshe-api.service`：`127.0.0.1:8000`
- `huagongshe-web.service`：`127.0.0.1:3001`
- Nginx：HTTPS、同域 `/api/*` 代理与 `www` 到主域跳转。

```bash
systemctl status huagongshe-api huagongshe-web nginx postgresql redis-server
curl -fsS https://huagongshe.com/api/health
```

API 连接信息由服务器上的 `/etc/huagongshe/api.env` 提供，不写入 Git。
