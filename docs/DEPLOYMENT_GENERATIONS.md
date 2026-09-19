# 计划部署与 generation 切换规范（2026-09-19 定案）

> 单一 owner：`ops/deploy.py`。本文是部署编排的行为契约；实现与本文冲突时修实现。
> 边界：本脚本**不**碰数据库 migration、不改 application 代码、不重定义 readiness 语义。

## 0. 关闭的缺陷

旧部署链 = `git ff-only` → `web build` → `pm2 reload <app>`，`ecosystem.config.cjs` 是 fork 模式
（非 cluster），nginx 又写死 `127.0.0.1:8000` / `127.0.0.1:3001`。fork 模式下 reload 等价于
"先停旧进程再起新进程"，于是固定 upstream 目标出现**无 owner 窗口** → nginx 502。

新序列把"两代同时存活"变成硬前提：先起新代 → readiness 通过 → 切 traffic → 验证新代
→ 才允许旧代退出。

## 1. Generation 模型（本机最小双代）

| generation | API app / port | web app / port | worker app |
|---|---|---|---|
| blue | `huagongshe-api` / 8000 | `huagongshe` / 3001 | `huagongshe-pubchem-worker` |
| green | `huagongshe-api-green` / 8010 | `huagongshe-green` / 3011 | `huagongshe-pubchem-worker-green` |

- blue = canonical 名字与端口（冷启动默认）；green = 名字加后缀、端口 +10。
- 每代是**独立三进程**：API、web（Next `next start`）、worker。
- worker 属于 generation：`HGS_WORKAPI_URL` / `HGS_WORKER_ID` 都指向本代
  （避免 worker 指向已停掉的旧代 API；两个 worker 短暂并存由服务端 lease 兜住）。
- PM2 spec 由 `ecosystem.config.cjs` **窄口径替换**得到（端口/名字/worker 指向 + `kill_timeout`）。
  锚点缺失或出现次数不符 = 漂移 → **fail-closed 拒绝生成**，绝不猜。
- generation spec 落在 `/var/lib/huagongshe/deploy/ecosystem-<gen>.cjs`（仓库外，不污染 checkout）。
- **每代独立的 Next 构建产物**：`web/next.config.ts` 的 `distDir` 读 `HGS_NEXT_DIST_DIR`
  （缺省 `.next`）；编排给每一代注入 blue → `.next-blue`、green → `.next-green`，
  构建与 `next start` 用**同一个值**（在 generation spec 的 env 里可见）。构建目标代不会碰到
  正在服务的旧代产物。
  - residual risk（已知并接受）：源码目录、`public/` 等仍共享。E8 只保证
    “generation-specific Next build artifact”，**不是**完全不可变的 release 目录。
  - `--skip-build` 的前提是目标代的 dist 目录已经构建过；否则 readiness 失败 → pre-switch 失败，
    旧代不受影响。

## 2. Readiness（真 HTTP，不是端口/进程）

- API 代：`GET http://127.0.0.1:<api_port>/api/health` 必须 `200` + `{"status":"ok"}`。
- web 代：`GET http://127.0.0.1:<web_port>/api/health`（经 Next BFF `app/api/[...path]`）必须同样通过
  —— 这同时证明 web 进程能服务 **且** 该 web 代连的是自己这一代的 API（`API_ORIGIN_INTERNAL`）。
- worker：`pm2 jlist` 里本代 worker `online`。
- 三者都过才算 ready；等待有界（默认 90s，可 `--readiness-timeout`）。
- `/api/health` 不依赖外部服务，因此不需要重新定义健康语义；它**不**校验 DB/Redis，
  本流程也不假装它校验。

## 3. Traffic switch（原子边界）

nginx 侧一次性 bootstrap（`install-nginx`，幂等、带备份、先 `nginx -t` 再 reload）：

- `/etc/nginx/hgs/generations/{blue,green}.conf` = `upstream hgs_api_active` / `upstream hgs_web_active`
- `/etc/nginx/hgs/generations/active.conf` = 指向当前代的 **symlink**（唯一切换点）
- site config 里 `proxy_pass http://127.0.0.1:8000|3001` → `proxy_pass http://hgs_api_active|hgs_web_active`，
  并在文件头 `include .../active.conf;`（该文件本身在 `http{}` 上下文）

切换三步：渲染候选 → **用临时 config 树** `nginx -t -c <tmp>/nginx.conf` 验证候选
（不动线上文件、不先破坏旧 upstream）→ 同目录 `symlink` rename（原子）→ `nginx -s reload`
→ **等到 applied**。

`nginx -s reload` 的 exit 0 只代表信号送达，**不等于**新配置已生效。判定由
`reload_and_wait_applied()` 给出：先抓 reload 前的 nginx worker PID，再发信号，有界等待
（`--reload-timeout`，默认 10s）master 仍存活 **且** 出现 reload 前不存在的 worker PID；
旧 worker 允许仍在 graceful drain，不要求它立即消失。只有 `switch.applied` 之后才允许
verify traffic → smoke → 停旧代。

失败处理：reload 信号失败 / 等不到新 worker / master 消失 / 探测不可用（`pgrep` 拿不到视图）
→ 一律按 switch 失败处理：symlink 恢复旧代 + **再次 reload 并等 applied**（只恢复 symlink
不算恢复）；这次恢复也没生效时 reason 带 `+restore-not-applied`。

## 4. Drain / 停旧代顺序

`traffic switch 成功` **且** `post-switch smoke 通过` 之后，才 `pm2 delete` 旧代三个 app
（SIGINT → `kill_timeout` 10s → SIGKILL，有界 graceful；本应用没有 connection-drain primitive）。
先给 `--drain-grace`（默认 5s）窗口让 nginx 旧 worker 的在途请求结束，再停旧代。
最后 `pm2 save`，使重启后恢复的是当前服务代。

## 5. 失败窗口

- **Pre-switch**（build / start / worker / readiness / nginx 校验 / reload 失败）：
  旧代继续服务，traffic 未动，新代被清理（`pm2 delete`）。旧代**从不**被停。
- **Post-switch**（traffic 验证 / smoke 失败）：恢复旧代 symlink → **再次 reload 并等 applied**
  → 验证旧代 → 停新代。旧代只有在 switch + smoke 都通过后才可能退出，所以不存在
  “旧代已停才发现问题”的窗口。
  - 若恢复用的 reload 也没生效：`stage = rollback-failed`、`old_verified = false`，
    **不清理新代**（运行中的 nginx 仍是新配置，新代必须继续服务），也不谎报旧代已恢复。
- **状态判定 fail-closed**：site config 里没有 generation include = PRE-BOOTSTRAP（现网固定端口）
  → 现网 = blue；已有 include = BOOTSTRAPPED → `active.conf` 必须存在且指向 `blue.conf`/`green.conf`，
  **缺失 / 坏链（目标文件不存在）/ 未知 target = DeployError**，部署绝不把 `None` 猜成 blue。
  `install-nginx` 重跑：已有合法 active → 保留当前 active（不重置成 blue）；无合法 active →
  初始化 blue；配置无变化 → 真幂等（不写文件、不 reload、不嵌套 include）。

## 6. Smoke（最小面）

公网入口（本机 nginx：`127.0.0.1:443` + `Host` 头）三项：readiness（`/api/health`）、
普通 HTTP（`/` 非空）、MCP 基本可达（`POST /mcp` initialize，`serverInfo.version` 必须等于 `VERSION`）。

## 7. 命令

```bash
python -m ops.deploy status                 # 只读: 当前代 + 两代 readiness
python -m ops.deploy install-nginx          # 一次性 bootstrap(幂等, 带备份+校验)
python -m ops.deploy --dry-run              # 只读计划: 不 build / 不 pm2 / 不 nginx / 不写文件
python -m ops.deploy --reload-timeout 20    # reload 后等待 applied 的上界(默认 10s)
python -m ops.deploy                        # 切到非当前代
python -m ops.deploy --to green --skip-build
```

退出码：`0` 成功 / `2` pre-switch 失败（旧代继续服务）/ `3` post-switch 回滚 / `1` 用法或校验错误。

## 8. 明确不做

- 不跑 migration（E2 生产索引 online precreate 属 E10 release procedure）。
- 不做多机 HA / LB 重设计 / 容器平台迁移 / PM2 或 nginx 架构重写。
- 不在 FastAPI application 里塞 generation 逻辑；application 只提供既有 readiness/HTTP/MCP 面。
- 不引入 release-directory framework / git worktree 部署 / 不可变 release store / 容器化；
  源码目录仍共享（见 §1 residual risk）。
