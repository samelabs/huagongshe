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

## nginx（一次性）

从 generation 拓扑迁回固定 upstream（幂等，日常发布不调用）：

```bash
python -m ops.deploy --nginx-bootstrap
```

流程：改写 site config 为固定 upstream → `nginx -t` → `nginx -s reload`。
备份写入 `/etc/nginx/hgs/`（include 目录之外）。
