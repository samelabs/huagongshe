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
