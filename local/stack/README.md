# 本地完整后端栈（hgs-local）

全本机 Docker 运行，与生产环境（huagongshe.com）**零连接**。照搬
`.github/workflows/ci.yml` integration job 的做法：

| 服务 | 镜像 | 说明 | 端口(仅 127.0.0.1) |
|---|---|---|---|
| db | ubuntu:24.04 + postgresql-16 + postgresql-16-rdkit | 集群在命名卷 `hgs_local_pgdata`；首次启动自动 initdb、建角色/库、跑 `migrations/0000_baseline.sql` + `0001_bootstrap_reference_data.sql`（hgs_local 与 test_hgs 两个库都建） | **55433** → 5432 |
| redis | redis:7 | 纯缓存/限流，不落盘 | **56380** → 6379 |
| api | python:3.12-slim + requirements.txt | 仓库根目录只读挂载 `/repo`；镜像内 apt 装 psql 客户端与 rdkit 绘图所需的 X11/expat 系统库；启动时装依赖到持久 venv、跑 `scripts/migrate.py`（两个库）、uvicorn 8000；含非 root 测试用户 `tester`(uid 1000) | **8000** |

> 端口 55432/56379 已被本机其他项目占用，故取相邻端口。
> 不启动 pubchem worker（本地不拉外部数据；化合物行由反应创建/SMILES
> 搜索时的 RDKit 本地建行产生）。

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

前端走仓库根的 `local/dev.sh`（见 ../README.md）。

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

## 跑测试（容器内、非 root、每 run 专有库）

后端测试不手写 docker exec 长命令、不共用 `test_hgs`。统一入口在仓库根：

```bash
python3 local/check.py backend --tests tests.<模块> …   # 最小模块集
python3 local/check.py release                          # 发布门禁(全量, 显式)
```

编排器自动完成：每 run 专有库 `test_hgs_<随机>`（baseline + bootstrap +
forward 迁移）、`TEST_DATABASE_URL`/`HGS_DATABASE_URL` 一致性预检、非 root
`tester` 执行、Redis 测试逻辑库 DB15 的 run 间串行、结束只清理本 run 登记
的资源。栈初始化建的共享 `test_hgs` 不再作为测试目标。细节见
`docs/TESTING.md`。

**验收脚本反复登录会撞限流**（login 限流 = 15 次 / 900s / 账号，redis 键
`rate:login:*`）。这是对演示栈(hgs_local 库)的人工运维操作，需要立刻重跑
演示脚本时清桶：

```bash
docker exec hgs_local_redis redis-cli --scan --pattern "rate:login*" | xargs -r docker exec -i hgs_local_redis redis-cli DEL
```

**种子幂等不重置"已读"**：点过动态页后 unread 变 0 且重跑 seed 不会恢复
（notifications.read_at 已写）。要恢复徽标场景：

```bash
docker compose --env-file .env.local exec db su postgres -s /bin/bash -c \
  "/usr/lib/postgresql/16/bin/psql -d hgs_local -c \"UPDATE community.notifications SET read_at=NULL WHERE event_type='new_reaction'\""
```

## 线上数据只读渲染（本地前端连生产 API）

需要用线上丰富数据（如 HCID 2244）检查 UI 时：另一份 checkout（Next 每目录
只允许一个 dev server），环境变量指向生产，**只做 GET、禁止登录与写操作**：

```bash
rsync -a --exclude node_modules --exclude .next web/ /tmp/hgs-prod/web/
cd /tmp/hgs-prod/web && npm ci
API_BASE=https://huagongshe.com/api API_ORIGIN_INTERNAL=https://huagongshe.com \
  npm run dev -- -p <任选空闲端口>
```

注意：生产 `/api/config` 会注入 51.la 统计与 AdSense 脚本，本机加载 403/挂起
会卡死 networkidle —— 截图工具需 route-block `sdk.51.la` /
`pagead2.googlesyndication.com`。

## 已知边界

- api 容器内仓库是**只读**挂载；任何需要写仓库文件的操作（如改代码）在宿主机做。
- Docker Desktop 内存约 2.9GB 且与其他项目容器共享；redis 限了 128MB，PG 未限。
- `scripts/migrate.py` 需要 psql（api 镜像已装 postgresql-client）。
- 测试用户 `tester` 缺失（`docker exec hgs_local_api id tester` 失败）说明镜像
  过旧：`docker compose --env-file .env.local up -d --build api` 重建。
