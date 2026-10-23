# 生产基线（PRODUCTION_BASELINE）

生产主机上"仓库之外"的运行前提与流程记录。`ops.deploy` 不自动变更这
里任何一项；本文件是安装、核对与发放凭证的权威清单。机密值（密码、
token、xray 上游凭据）一律不入库，只记录位置与形态。

## 1. 部署用户与 sudoers 免密放行

- 部署用户（deployment user）：生产上的普通用户（非 root），PM2 以该
  用户运行全部三个 app（`huagongshe-api` / `huagongshe` /
  `huagongshe-pubchem-worker`，与 `ecosystem.config.cjs` 的 canonical 名一致）。
- `ops.deploy` 全程以该用户执行；**唯一**的特权操作是 nginx 相关的单独
  `sudo -n`，sudoers 精确放行以下四条（均带 NOPASSWD）：

```
Cmnd_Alias HGS_NGINX = \
    /bin/cp /etc/nginx/sites-enabled/huagongshe /etc/nginx/hgs/huagongshe.pre-single-*.bak, \
    /bin/cp /tmp/hgs-site-*.conf /etc/nginx/sites-enabled/huagongshe, \
    /usr/sbin/nginx -t, \
    /usr/sbin/nginx -s reload
<deployment-user> ALL=(root) NOPASSWD: HGS_NGINX
```

  注意：`sudo python -m ops.deploy` 被脚本明确拒绝——部署脚本本身必须
  以普通用户运行，只有 nginx 校验/重载单独提权。`/etc/nginx/hgs/` 目录
  存放 bootstrap 的自动备份。

## 2. 只监听回环的端口清单与主机防火墙

以下服务只绑 `127.0.0.1`（或 unix socket），公网必须不可达：

| 端口 | 服务 | 说明 |
|---|---|---|
| 8000 | FastAPI（huagongshe-api） | 仅经 nginx `/api/`、`/mcp`、`/data/` 转发 |
| 3001 | Next（huagongshe） | 仅经 nginx `/` 转发 |
| 6379 | Redis | 限流/缓存/nonce（DB 1 运行、DB 15 测试） |
| 5432 | PostgreSQL 16 | 业务库 |
| 12345 | xray SOCKS（PubChem 出口） | worker 主数据链路依赖 |
| 12346 | xray SOCKS（ChemicalBook 出口） | 同上 |

ufw 默认拒绝入站，只放行 22/80/443（及 ICMP）；3001、8000 等端口
不单独放行。核对方法：

```
sudo ufw status verbose
ss -tlnp | grep -E ':(8000|3001|6379|5432|12345|12346)\b'
# 期望全部只出现在 127.0.0.1 行
```

## 3. PostgreSQL 参数（ALTER SYSTEM 级）

生产实际值（`pg_settings` 快照，PG 16.15）：

| 参数 | 值 |
|---|---|
| shared_buffers | 2621448kB ≈ 2.5GB |
| effective_cache_size | 6553608kB ≈ 6.25GB |
| maintenance_work_mem | 262144kB = 256MB |
| work_mem | 32768kB = 32MB |
| effective_io_concurrency | 200 |
| random_page_cost | 1.1 |
| jit | off |
| track_io_timing | on |
| log_min_duration_statement | 1s |
| statement_timeout | 8s |
| idle_in_transaction_session_timeout | 0 |
| max_connections | 100 |

`max_connections=100` 的连接预算：API 进程 2 × uvicorn worker ×
(pool 5 + 溢出 5) = 20；worker（aiohttp 并发但 SQL 会话串行）≈ 6；
migrate/admin/运维连接与 psql 手工操作 ≈ 10；余量 ≥ 60 留给突发与
重连风暴。超预算的症状是 `FATAL: too many connections`——先查
`pg_stat_activity` 的 idle in transaction，不要直接调大 max_connections。

## 4. needrestart（mode l）

`/etc/needrestart/conf.d/hgs-list-only.conf`：`$nrconf{restart} = 'l';`
——自动安全更新照常安装，但 needrestart **只列出**需要重启的服务、不
自动重启（防止升级后随机重启 pm2 造成整站中断）。需要重启的服务在部
署/维护窗口用 `needrestart -r l` 查看后统一处理。

## 5. PM2 宿主与开机自启

- 开机自启唯一来源：`pm2 startup`（以部署用户执行）生成的 systemd unit
  `pm2-<deployment-user>.service` + `pm2 save` 的 dump（`~/.pm2/dump.pm2`）。
  发布流程末尾自动 `pm2 save`。
- 已存在 app 的重启必须带 ecosystem 路径：`pm2 restart ecosystem.config.cjs
  --only <app> --update-env`（否则 env 变更不生效）。
- 验证：重启 `pm2-<deployment-user>.service`，确认三个 app 自动恢复。

## 6. xray-pb 出口服务（worker 采集链路依赖）

- systemd unit：`ops/systemd/xray-pb.service`（入库）。配置文件
  `/home/ubuntu/ops/xray-bin/config.json` **含上游凭据，不入库**；二进
  制与配置都在该目录。
- 用途：本机 SOCKS5 出口 `socks5://127.0.0.1:12345`（PubChem 链）与
  `:12346`（ChemicalBook 链）。本机直连出口 IP 已被 PubChem 封禁，
  `HGS_PUBCHEM_PROXY` 未设置时 worker 的 pubchem 通道禁用并持续 ERROR
  日志、循环空转（不是崩溃）。
- 依赖关系：unit `Before=pm2-ubuntu.service`（worker 起来时代理必须已
  就绪）；`ExecStartPost` 探测两个端口就绪才算启动成功；`Restart=always`。
- 故障表现：worker 日志出现 `HGS_PUBCHEM_PROXY unset — pubchem
  disabled` 或大量请求超时 → 查 `systemctl status xray-pb` 与端口探活。

## 7. worker 凭证注册流程

1. 管理员在站内管理端（或 `POST /api/admin/workers`，admin 会话）登记
   worker：`worker_id` + `token`（明文只在登记时给一次，库里只存哈希）
   + scopes（`pubchem` / `cas`）。
2. 把 `HGS_WORKER_TOKEN`、`HGS_WORKER_ID`、`HGS_WORKAPI_URL`
   （`http://127.0.0.1:8000`）写进 worker 运行环境（PM2 env）。
3. 重启 `huagongshe-pubchem-worker`；启动日志必须出现 `auth preflight ok`——preflight
   失败会 crash-loop（设计如此：凭证不对不允许领取任务）。
4. 发放顺序：**先注册凭证再起 worker**（顺序颠倒会造成启动风暴）。

## 8. 服务 API（/data/v1）凭证签发流程

1. 管理员 `POST /api/admin/data-clients`（管理端"数据凭证"面板）：
   提交名称、联系人、scopes（`data:chemical:read` / `data:reaction:read`）、
   分钟/天额度、可选到期时间。
2. 响应里的 `client_id`（`hgsd-` 前缀）与 token **明文只返回一次**；
   告知调用方妥善保存（库里只存哈希）。
3. 停用/调额：`PATCH /api/admin/data-clients/{id}`（enabled、额度、到期）。
4. 调用方按 `/data-api` 文档页签名调用；nonce 防重放依赖 Redis 持久化
   （重启不丢窗口内 nonce）。

## 9. 依赖 Cloudflare 的行为（要求与核对方法）

以下行为依赖 Cloudflare 侧配置正确，仓库与源站无法单独保证：

- **真实 IP 传递**：DNS 必须橙云代理；nginx `cloudflare-realip.conf` 的
  `set_real_ip_from` 网段必须覆盖 Cloudflare 当前全部网段。核对：站内
  任意登录后看会话与限流是否正常；`curl` 直连源站 IP 应被 444 拒绝
  （未过 CF 的直达不可信）。
- **匿名页缓存规则**：源站对匿名公开页输出 `Cache-Control: public`、
  对 RSC/预取请求输出 `private, no-store`（Cloudflare 不识别 `Vary: rsc`）。
  CF 的 Cache Rule 需放行这些 HTML 的缓存并**尊重源站头**——带
  `no-store` 的响应不得进边缘缓存。核对：匿名访问详情页两次，第二次
  `cf-cache-status: HIT`；登录访问必须 MISS/DYNAMIC。
- **图片缓存**：`/img/*`（mol PNG/SVG）依赖 CF 按源站 `Cache-Control`
  缓存；核对响应头的 `cf-cache-status`。
- **部署冒烟 UA 放行**：bot 规则需放行 `Huagongshe-Deploy-Smoke/1.0`
  （部署后公网冒烟用它过 bot 防护）；核对：带该 UA 请求 `/api/health`
  返回 200。
- TLS 模式需与源站证书匹配（Full (strict) 对应 letsencrypt 证书）；
  核对：浏览器访问无证书告警、HTTP/2 生效。

以上只写要求与核对方法；当前账户侧的具体规则值以 Cloudflare 控制台
为准，不在仓库内复制。
