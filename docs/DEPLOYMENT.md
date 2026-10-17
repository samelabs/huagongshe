# 部署（单实例 SSOT）

> v1.5.2 R4-SINGLE 起，蓝绿/generation 机制已整体移除。本文是部署的唯一规范来源。
> 历史：blue/green 编排（E8–E10）在生产暴露多处单机环境偏差（PM2 daemon 归属、
> spec 文件识别、worker 预注册）后，决策放弃单机 zero-downtime，回归单实例。

## 模型

- **单实例**：一个 API、一个 Web、一个 worker，无备用代。
- **固定端口**：API `127.0.0.1:8000`，Web `127.0.0.1:3001`。
- **单一 PM2 owner**：唯一非 root deployment user 拥有 daemon 与三 app。
  root 不运行 PM2（曾导致 green app 落 root daemon、blue 无法被 drain）。
- **单一 canonical spec**：仓库根 `ecosystem.config.cjs` 是运行时唯一定义，
  不生成任何派生 spec（`server-local-1-green/blue` 等名字不复存在）。
- **单一 Next 构建**：`web/.next`（默认 distDir），无 `.next-blue/.next-green`。
- **Worker 身份固定**：`HGS_WORKER_ID=server-local-1`，
  `HGS_WORKAPI_URL=http://127.0.0.1:8000`，
  与 `maintenance.worker_clients` 注册行一一对应，不随部署改名。
- **nginx 固定 upstream**：`hgs_api → 127.0.0.1:8000`、`hgs_web → 127.0.0.1:3001`。
  拓扑不随发布重写；无 `active.conf`/generation symlink。

## 维护窗口

**不承诺 zero-downtime**：每次发布 restart 三 app，接受短暂维护窗口（秒级）。
发布避开高峰执行即可；无自动流量切换、无 rollback state machine。

## 发布流程

deployment user（非 root）执行：

```bash
# 1) 先迁移（顺序不可倒）：对生产库应用未执行的 migrations/ 文件。
#    本批及此前的迁移均对旧代码向后兼容，迁移先行零风险；
#    反序（新代码 + 旧 schema）会导致 CB 摄入、OAuth 注册等落库路径直接故障。
python scripts/migrate.py "<生产 DATABASE_URL>"   # 与 api 进程 HGS_DATABASE_URL 同一库

# 2) 部署
python -m ops.deploy                 # build → restart 三 app → readiness → smoke → pm2 save
python -m ops.deploy --skip-build    # 跳过 Web 构建
python -m ops.deploy --dry-run       # 只打印计划
```

owner 职责仅限：root guard → build Web → 按 CanonicalApps 逐个
`pm2 start ecosystem.config.cjs --only <app>`（不存在时）或 `pm2 restart <app>`（已存在时）
→ readiness（API 8000 health / Web 3001 health / worker online，均有界等待）
→ public smoke（canonical HTTPS `https://huagongshe.com/api/health`：一次请求验证
nginx vhost + TLS + API upstream 整链；非 200 / body 异常 / 网络错误 fail closed）
→ `pm2 save`。

失败语义：任一步失败 → 非零退出、不伪报 success；不自动回滚（人工决策）。

**root guard**：`sudo python -m ops.deploy` 直接 fail-closed。必要的 nginx/system
操作（`nginx -t`、`nginx -s reload`）由 owner 内部单独 `sudo -n` 执行。

## reboot persistence

唯一来源：deployment user 的 PM2 systemd unit
（`pm2-<deployment-user>.service`，`pm2 startup` 生成）+ `pm2 save` 的 dump。
发布流程末尾自动 `pm2 save`。验证方式：重启该 systemd unit，确认三 app 自动恢复。

## receipt retention（WorkAPI 完成回执清理）

- 契约：retention **30 天**、batch **10000**、逐批 DELETE + commit、dry-run 支持。
- 唯一生产调度：`ops/systemd/huagongshe-receipt-prune@<deployment-user>.timer`
  （systemd template，不硬编码用户名）—— daily + `Persistent=true` +
  `RandomizedDelaySec=30m`；非零退出由 systemd 记为 failed。
- 仓库内不存在第二套 receipt scheduler 定义。

## OAuth credential retention（过期凭证清理，F-06/B5-09）

- 契约：grace **7 天**（过期/撤销后保留短窗供 invalid_grant 归因与故障调查）、
  batch **10000**、逐批 DELETE + commit、dry-run 支持。
- 覆盖四表：`oauth_authorization_requests` / `oauth_authorization_codes`
  按 `expires_at`；`oauth_access_tokens` / `oauth_refresh_tokens` 按
  `expires_at` 或 `revoked_at`（撤销 ≠ 立即删，同留 grace）。
- 唯一生产调度：`ops/systemd/huagongshe-oauth-prune@<deployment-user>.timer`
  （与 receipt prune 同口径：daily + `Persistent=true` +
  `RandomizedDelaySec=30m`，非零退出记 failed）。

## skill tombstone retention（删除残留清扫，P2c）

- 契约：grace **7 天**，按 `.deleted-*` 目录 mtime 判断（注意：rename 保留原目录 mtime，
  刚删除的老技能目录可能立刻超出 grace；删除补偿窗口极短，运维上避免与删除操作同时手动执行），只扫 skill_root 下一层
  `.deleted-*` 目录，dry-run 支持，FS 错误非零退出。
- 唯一生产调度：`ops/systemd/huagongshe-skill-tombstone-sweep@<deployment-user>.timer`
  （与 receipt/oauth prune 同口径：daily + `Persistent=true` +
  `RandomizedDelaySec=30m`）。

## nginx（一次性）

从 generation 拓扑迁回固定 upstream（幂等，日常发布不调用）：

```bash
python -m ops.deploy --nginx-bootstrap
```

流程：改写 site config 为固定 upstream → `nginx -t` → `nginx -s reload`。
备份写入 `/etc/nginx/hgs/`（include 目录之外）。

### 数据服务接入（/data/ 直连 FastAPI，不经过 Next）

生产 nginx vhost 需要新增以下 location（由 PM 在生产执行；`ops.deploy`
不自动修改）：

```nginx
# 对外数据服务(/data/v1)直接转发给 FastAPI;
# 该接口自带凭证鉴权(HMAC 签名 + nonce 防重放)与按凭证计量。
# limit_req 补齐"无效凭证刷鉴权"的边界: 鉴权失败不占凭证额度, 应用侧
# 另有 per-IP 失败桶(api/data_api.py AUTH_FAIL_*), nginx 层先挡量级洪水。
# $binary_remote_addr 经 cloudflare-realip 后即真实访客 IP。
limit_req_zone $binary_remote_addr zone=hgs_data_api:10m rate=10r/s;  # http {} 级
location /data/ {
    limit_req zone=hgs_data_api burst=20 nodelay;
    proxy_pass http://hgs_api;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For "";
}
```

## 生产配置（只列出不自动变更的项，I-070）

本节只是生产机配置的**记录与核对清单**——`ops.deploy` 不会自动修改这些参数；
部署时在生产环境执行变更与核对。与仓库默认不同的 PG 参数（`ALTER SYSTEM` 级）：

| 参数 | 生产值 | 说明 |
| --- | --- | --- |
| `work_mem` | 32MB | 结构检索/名称检索排序内存 |
| `jit` | off | 稳定计划延迟（OLTP 场景禁用 JIT 编译开销） |
| `log_min_duration_statement` | 1s | 慢查询日志阈值 |
| `effective_io_concurrency` | 200 | NVMe 语境的预读并发 |
| `track_io_timing` | on | I/O 计时（`pg_stat_statements` I/O 归因） |
| `shared_buffers` | 2GB | 实例内存配额下的 PG 共享缓冲 |

`ALTER SYSTEM` 参数存放于 `postgresql.auto.conf`；`shared_buffers` 调整需重启
PG 方能生效，其余为 reload 级。

**needrestart**（Debian/Ubuntu 自动重启策略）：生产配置为**只列出、不自动重启**
的模式——包升级后需要重启的服务（含 PG major 升级后的 `postgresql`、`nginx` 等）
只出现在 needrestart 报告里，由值班人按维护窗口人工决定；`ops.deploy` 的 pm2 托管
应用不经过 needrestart。

### 公网冒烟（部署后必过，任一失败 deploy 非零退出）

1. `GET https://huagongshe.com/api/health` → 200 + `status=ok`
2. 五种语言首页 `/{zh-CN,en,ja,ko,de}` → 各 200
3. `GET https://huagongshe.com/en/chemical/4`（HCID 4 详情页）→ 200
4. `POST /mcp` initialize → `serverInfo.version` 必须等于仓库 `VERSION` 文件
