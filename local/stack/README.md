# 本地完整后端栈（hgs-local）

全本机 Docker 运行，与生产环境（huagongshe.com）**零连接**。照搬
`.github/workflows/ci.yml` integration job 的做法：

| 服务 | 镜像 | 说明 | 端口(仅 127.0.0.1) |
|---|---|---|---|
| db | ubuntu:24.04 + postgresql-16 + postgresql-16-rdkit | 集群在命名卷 `hgs_local_pgdata`；首次启动自动 initdb、建角色/库、跑 `migrations/0000_baseline.sql` + `0001_bootstrap_reference_data.sql`（hgs_local 与 test_hgs 两个库都建） | **55433** → 5432 |
| redis | redis:7 | 纯缓存/限流，不落盘 | **56380** → 6379 |
| api | python:3.12-slim + requirements.txt | 仓库根目录只读挂载 `/repo`；镜像内 apt 装 psql 客户端与 rdkit 绘图所需的 X11/expat 系统库；启动时装依赖到持久 venv、跑 `scripts/migrate.py`（两个库）、uvicorn 8000 | **8000** |

> 端口 55432/56379 已被本机其他项目占用，故取相邻端口。
> 不启动 pubchem worker（本地不拉外部数据；化合物行由反应创建/SMILES 搜索时的 RDKit 本地建行产生）。

凭据全部是随机生成的本地假值，在 `stack/.env.local`（不入库）：DB 密码、
`hgs_demo` / `hgs_peer` 两个测试账号密码。

## 起停

```bash
cd local/stack
docker compose --env-file .env.local up -d          # 起（首次会 build + initdb + pip install，几分钟）
docker compose --env-file .env.local ps             # 状态
docker compose --env-file .env.local logs -f api    # 看 api 日志（迁移/uvicorn）
curl http://127.0.0.1:8000/api/health               # 应返回 ok
docker compose --env-file .env.local down           # 停（数据保留在卷里）
```

前端（默认连 127.0.0.1:8000，无需 API_BASE）：

```bash
cd web && npm run dev -- -p 3104    # 每轮验收换新端口，避开浏览器旧 CSS 缓存
```

## 重置数据库

```bash
docker compose --env-file .env.local down -v        # -v 删数据卷（DB 数据 + venv + pip 缓存）
docker compose --env-file .env.local up -d          # 重新 initdb + baseline
python3 seed.py                                     # 重新种子
```

只重置数据库不动 venv：`docker volume rm hgs-local_hgs_local_pgdata` 后 `up -d`。

## 种子数据

```bash
python3 seed.py    # 幂等，重复执行数据不变
```

只通过 HTTP API 写入（`127.0.0.1:8000`），不直接写库。账号：

- `hgs_demo`（SUN Demo）：2 条公开反应（阿司匹林合成 / Fischer 酯化）+ 1 条私有反应、
  2 篇笔记（公开关联 HCID+HRID、私有关联 HCID）、收藏 3 个化合物、关注 hgs_peer
- `hgs_peer`（Lin Demo）：2 条公开反应（水杨酸甲酯 / 阿司匹林水解，触发 demo 的
  new_reaction 动态）、关注 hgs_demo

密码在 `.env.local`（`SEED_HGS_DEMO_PASSWORD` / `SEED_HGS_PEER_PASSWORD`）。
反应用固定 `Idempotency-Key`（`seed-*`），笔记先查重，follow 类端点 ON CONFLICT——
三者共同保证幂等（已验证连跑两次 HRID/笔记 id/收藏/动态数完全不变）。
本轮实际种出的编号：demo 公开反应 HRID 1（阿司匹林合成）/ 3（Fischer 酯化）、
私有 HRID 2；peer 公开 HRID 4（水杨酸甲酯）/ 5（阿司匹林水解）；
笔记 id 1/2；收藏 HCID 4（阿司匹林）/ 1（水杨酸）/ 10（水杨酸甲酯）；
demo 动态 2 条（peer 的两条公开反应）。

## 跑完整测试套件（CI 同款）

与 CI 对齐的四个要点：**venv python**（`/opt/venv/bin/python`，容器系统 python 没有依赖）、
**非 root 用户** `tester`（部分故障注入测试在 root 下不生效，CI runner 是非 root）、
**HGS_PUBLIC_BASE_URL 对齐 CI 默认值**（不设即默认 `https://huagongshe.com`；本地
runtime 用 localhost 是故意的，跑测试时覆盖回来）、**干净的 test_hgs**（CI 每次全新库；
连跑两轮套件后 planner 类断言会被残留数据影响，重跑前先按下面命令重置）。

**重置 + 全套一条龙（step6 起为本目录标准入口；用户要求 = tester 非 root、
venv python、HGS_PUBLIC_BASE_URL 对齐 CI、pristine test_hgs）：**

```bash
cd local/stack
PW=$(grep HGS_DB_PASSWORD .env.local | cut -d= -f2)

# 1) 重置 test_hgs 到 pristine（baseline + bootstrap + migrate）
docker compose --env-file .env.local exec db su postgres -s /bin/bash -c \
  "/usr/lib/postgresql/16/bin/psql -c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='test_hgs' AND pid<>pg_backend_pid()\"; /usr/lib/postgresql/16/bin/dropdb test_hgs; /usr/lib/postgresql/16/bin/createdb -O hgs_local test_hgs"
docker compose --env-file .env.local exec db bash -c \
  "PGPASSWORD=$PW psql -h 127.0.0.1 -U hgs_local -d test_hgs -v ON_ERROR_STOP=1 -f /repo/migrations/0000_baseline.sql >/dev/null && PGPASSWORD=$PW psql -h 127.0.0.1 -U hgs_local -d test_hgs -v ON_ERROR_STOP=1 -f /repo/migrations/0001_bootstrap_reference_data.sql >/dev/null"
docker compose --env-file .env.local exec api python /repo/scripts/migrate.py "postgresql://hgs_local:$PW@db:5432/test_hgs"

# 2) 清掉以 root 跑过测试留下的 /tmp 残留（否则 tester 下 setUpClass PermissionError）
docker compose --env-file .env.local exec api rm -rf /tmp/hgs-admin-pagination-test

# 3) 全套（discover tests）
docker compose --env-file .env.local exec -u tester -e HOME=/home/tester \
  -e TEST_DATABASE_URL="postgresql+asyncpg://hgs_local:$PW@db:5432/test_hgs?test_sentinel=hgs-test-db" \
  -e HGS_DATABASE_URL="postgresql+asyncpg://hgs_local:$PW@db:5432/test_hgs" \
  -e HGS_REDIS_URL="redis://redis:6379/15" \
  -e HGS_SKILL_ROOT=/tmp/hgs-skills \
  -e HGS_PUBLIC_BASE_URL=https://huagongshe.com \
  api bash -lc 'cd /repo && /opt/venv/bin/python -m unittest discover -s tests'
```

测试库是 db 容器里单独的 `test_hgs`（带 `?test_sentinel=hgs-test-db` 哨兵，
`tests/db_gate.py` 强制），与运行库 `hgs_local` 互不污染。

**验收脚本反复登录会撞限流**：login 限流 = 15 次 / 900s / 账号（redis 键
`rate:login:*`）。需要立刻重跑时清桶：

```bash
docker exec hgs_local_redis redis-cli --scan --pattern "rate:login*" | xargs -r docker exec -i hgs_local_redis redis-cli DEL
```

**种子幂等不重置"已读"**：点过动态页后 unread 变 0 且重跑 seed 不会恢复
（notifications.read_at 已写）。要恢复徽标场景（ix-check 场景 7 内置了这一步）：

```bash
docker compose --env-file .env.local exec db su postgres -s /bin/bash -c \
  "/usr/lib/postgresql/16/bin/psql -d hgs_local -c \"UPDATE community.notifications SET read_at=NULL WHERE event_type='new_reaction'\""
```

**pristine test_hgs 上的本轮结果（Step 6，2026-10-10）**：`Ran 1478 tests …
FAILED (failures=1, errors=1, skipped=1, expected failures=1)`。两个非预期项
都是"开发机 checkout vs CI checkout"的环境差异，不是代码问题（step3 起持续，
两轮 pristine 复跑均复现同样两项）：
`test_no_masked_placeholder_leaked_into_sources` 扫到宿主 `.venv/`（CI checkout 没有）；
`test_chemical_name_resolver.ResolverRuleTests` setUpClass 跑宿主 `web/node_modules`
里的 tsx/esbuild（darwin 二进制在 linux 容器里不可用；CI integration 无 web deps 时
该测试走 skip 分支）。除这两项外 0 失败。

## 登录截图（shoot.mjs）

```bash
cd ../  # _(已收编至 local/stack)_/tools
node shoot.mjs --base http://localhost:3104 --out ../ui/step3/local \
  --pages 'aichem=/zh-CN/aichem' --widths 1440,375 --login hgs_demo
```

`--login` 仅允许 localhost 目标；用页面表单真实登录（每宽度一个 context 登录一次），
密码取自 `stack/.env.local`。会话 cookie 带 Secure 标记，Chromium 在
http://localhost 下接受（localhost 是安全上下文）。

## 线上数据只读渲染（本地前端连生产 API）

需要用线上丰富数据（如 HCID 2244）检查 UI 时：另一份 checkout（Next 每目录
只允许一个 dev server），环境变量指向生产，**只做 GET、禁止登录与写操作**：

```bash
rsync -a --exclude node_modules --exclude .next web/ /tmp/hgs-prod/web/
cd /tmp/hgs-prod/web && npm ci
API_BASE=https://huagongshe.com/api API_ORIGIN_INTERNAL=https://huagongshe.com \
  npm run dev -- -p 3107
```

注意：生产 `/api/config` 会注入 51.la 统计与 AdSense 脚本，本机加载 403/挂起
会卡死 networkidle —— 截图工具需 route-block `sdk.51.la` / `pagead2.googlesyndication.com`
（见 tools/step6-shoot.mjs）。

## 已知边界

- api 容器内仓库是**只读**挂载；任何需要写仓库文件的操作（如改代码）在宿主机做。
- Docker Desktop 内存约 2.9GB 且与其他项目容器共享；redis 限了 128MB，PG 未限。
- `scripts/migrate.py` 需要 psql（api 镜像已装 postgresql-client）。
