# HGS 测试手册(权威)

本文件是开发与测试运行的**唯一权威手册**。AGENTS 保留强制摘要并链接到此;
CONTRIBUTING、local/README、local/stack/README、CI 只作场景入口, 不再复制
环境变量、全量口径或历史命令。任何入口行为变化先改这里, 再同步实现。

## 1. 唯一检查入口

仓库根执行 `python3 local/check.py <子命令>`(宿主 Python ≥3.9 标准库即可,
编排器不依赖 asyncpg/rdkit; 真正的检查在既有工具里跑)。

| 子命令 | 用途 | 关键行为 |
|---|---|---|
| `preflight` | 只读环境盘点 | 列 cwd/HEAD/脏文件/分支/版本/容器/UID/端口/互斥状态; 不写库、不杀进程、不装包、不打印秘密 |
| `web` | 前端四件套 | 宿主 Node 跑 `tsc --noEmit`、`test:unit`、`test:locale`、`check:api-layer`; 默认不 build、不全站截图 |
| `backend --tests tests.<模块>…` | 后端最小模块集 | 容器 `/opt/venv` 内、非 root `tester` 下跑**显式**模块; 每 run 专有测试库; 空选择/未知模块非零退出, 不 fallback 全量 |
| `worker` | 干净 worker 环境 | api 容器内一次性 venv 只装 `requirements-worker.txt`, 跑 `scripts/check_worker_imports.py`; 自证不读应用 site-packages |
| `release` | 显式发布门禁 | 冻结 SHA → 专有库全量后端 → web → production build → worker; `--dry-run` 只列计划。发版时执行 |

**退出码合同**: `0=PASS`(该阶段真实完成) · `1=FAIL`(断言/命令失败) ·
`2=BLOCKED`(环境/依赖未就绪、超时、模块缺失) · `3=用法错误`(空选择、
非法模块名、cwd 不在本仓库树)。CI 与脚本以退出码为准, 不看终端末尾字样。

**结果合同**: 每个 run 写 `local/.check-runs/<run_id>/`(不入 git): 每步
`*.out/*.err` 脱敏日志 + `result.json`(run_id、起止时间、HEAD 与脏文件
标记、命令参数、cwd、runtime 版本、UID、数据库/Redis 资源标识(无密码)、
逐步 exit_code、用例总数、skip/xfail 逐项、清理状态)。日志与结果中的
连接串一律去密码; `PGPASSWORD` 只经 docker `-e` 注入, 不进任何文件。

**cwd 纪律**: 在仓库树内任意位置调用会自动切回仓库根并记录原 cwd;
在别的树上调用直接拒绝(退出 3), 不静默跑另一套树。

## 2. 环境

### 本地(唯一受管形态)

- 栈: `local/stack`(docker compose: db 55433 / redis 56380 / api 8000, 全部
  127.0.0.1), 前端唯一入口 `local/dev.sh`。栈不在跑时编排器记 BLOCKED,
  **不替用户起栈**。
- 后端测试解释器: api 容器 `/opt/venv/bin/python`(Python 3.12); 宿主
  Python 只做编排。测试以非 root `tester`(uid 1000)执行 — root 下部分
  文件权限故障注入测试不生效; 容器缺 `tester` 说明镜像过旧, BLOCKED 并
  提示 rebuild。
- 前端: 宿主 Node ≥22 系列(CI 基准 22; strip-types 必须可用), npm 在
  PATH; `web/node_modules` 缺失时 BLOCKED(先 `npm ci`)。
- 凭据只从 `local/stack/.env.local` 读入编排器内存; 演示账号口令同源,
  不硬编码进文档或命令行历史。

### CI(GitHub Actions, ubuntu-24.04)

- `core` job: Python 3.12 + Node 22, 纯快检(显式模块清单, 无 DB)。
- `integration` job: PG16+RDKit cartridge + Redis7 容器服务; baseline +
  bootstrap + forward 迁移后全量 discover; 显式设置两个数据库 URL 指向
  同一库、canonical `HGS_PUBLIC_BASE_URL=https://huagongshe.com`、临时
  skill 目录。hosted runner 本身非 root。
- CI 不依赖本地 Docker Desktop; 本地也不假定宿主装有 asyncpg。新增 Python
  测试由 integration discover 覆盖；前端 runtime 测试由 `web/test-suites.json` 分组并校验遗漏/重复 — 纯快检清单只做
  提速, 不做准入边界。

## 3. 测试分级(最小充分集)

按改动类型选最小充分集, 不随手跑全量; 全量只在 CI 与 release 门禁各一次。

| 改动类型 | 必跑 |
|---|---|
| 只改文案 | `check.py web` 中的 `test:locale` + `tsc` |
| 改前端组件/样式 | 再加 `test:unit`、`check:api-layer`、`tests.test_ui_token_contract`、`tests.test_style_ratchet`, 只截改到的页面 |
| 改后端 | `check.py backend --tests tests.<涉及模块>…` + 直接相关回归 |
| 数据库迁移 | 专有库经 `scripts/migrate.py` 正向执行一次(release/集成前的迁移批); 不可改已应用迁移 |
| 改依赖/构建/runner | 相关构建与干净 worker 检查(`check.py worker`); 锁文件与 CI 同步 |

跨全局契约变更(错误包络、对外接口面、删除符号)不适用上表最小集: 用
`grep -rn "旧符号" tests/ web/` 找全调用方与测试, 逐个跑齐, 否则 CI 才
批量暴露。

测试归属: 前端纯函数测试放 `web/lib` 下用 node:test/tsx; Python 测试
承载后端与必要架构契约。夹具由测试自建自清理, 禁止依赖执行顺序、演示
账号固定 id 或库里恰好存在的样本。

## 4. 数据库与 Redis 隔离

1. `backend`/`release` 每次运行自动生成 `test_hgs_<随机>` 专有库(名字
   落在 `tests/db_gate.py` 的名称模式内), 经 db 容器管理身份 createdb,
   由应用账号执行 baseline + bootstrap, 再由 api 容器经
   `scripts/migrate.py` 执行 forward(迁移 URL 为原生 scheme、不带
   sentinel — libpq 不认 sentinel 参数)。
2. 测试子进程环境在启动前构造并**预检一致**: `TEST_DATABASE_URL`(带
   sentinel)与 `HGS_DATABASE_URL` 解析后的 host/port/username/database
   必须一致, 不一致在连接与任何 DDL 之前拒绝。宿主残留的同名环境变量
   不会泄入(编排器显式覆盖)。
3. `tests/db_gate.py` 的名称模式 + sentinel 双闸继续作为测试文件级防线;
   编排器的预检不替代它。
4. 管理身份(postgres)只用于建/删本 run 专有库; 运行身份是应用账号,
   OS 层非 root 是另一重独立约束, 报告分别记录。
5. Redis 用测试逻辑库 `redis://redis:6379/15`; 编排器以主机侧文件锁
   (主机临时目录的 `hgs-check-redis-db15.lock`, 跨 checkout 共用)串行化使用同一逻辑库的 run。
   手工在容器里跑测试时不得与编排器 run 并发。禁止 FLUSHDB。
6. 清理只认本 run 登记的资源(专有库、容器 /tmp 目录): dropdb 前目标名
   必须匹配专有库模式, 不按 `test_*` 通配删、不终止他人会话、不动演示库
   `hgs_local`/`test_hgs`、不删用户 venv 或 `.next`。失败时清理失败单独
   列出残留位置。迁移破坏性 runner 测试只在专有库进行。

## 5. web 检查与 build/dev 互斥

- `web` 子命令不 build; production build 只进 release 门禁。
- 同一 checkout 上 `next dev` 与 `next build` 共用 `web/.next`, 并发互
  相破坏。互斥机制:
  - dev 与 build 共同持有 `local/.check-runs/next-output.lock` 原子文件锁，覆盖子进程生命周期；PID JSON 只作诊断。第二个 dev/build 拒绝启动。
  - release 的 build 阶段前查互斥: 标记存活即 BLOCKED; 标记对应的进程
    已死视为残留, 清理后继续; 端口 3000 有监听时保守拒绝(覆盖旧标记
    机制之前启动的 dev), 不猎杀进程 — 由操作者停 dev、腾端口或改用
    隔离 checkout。
- 线上数据只读渲染用**另一份 checkout**(见 local/stack/README), 不与
  开发 checkout 混用 dev server。

## 6. worker 干净环境

`check.py worker`: api 容器内一次性 venv(`python3 -m venv`, 无系统
site-packages), 只装 `requirements-worker.txt`(aiohttp、aiohttp-socks、
rdkit), 运行 `scripts/check_worker_imports.py`(解析 worker 全部 import,
含函数级)。安装走容器内持久轮子缓存(tester 家目录, 复用已下载轮子);
宿主 `PIP_INDEX_URL` 透传注入镜像(仓库默认官方源)。安装/执行有界
(默认 900s/300s, 可调); 超时或失败如实记 BLOCKED/FAIL — 应用 venv 的
通过不能冒充干净环境通过。CI core job 在 hosted runner 上做同一检查。

## 7. release 门禁(显式)

`python3 local/check.py release`(可选 `--dry-run` 只列计划)。阶段:

1. freeze: 记录 HEAD、受测内容指纹与脏文件；阶段间和结束复核，代码变化则本轮作废。未提交改动只作 working-tree 证据。容器 /repo 必须属于当前 checkout，建库前核实。
2. mutex-guard: dev/build 互斥(见 §5)。
3. fresh-db: 新专有库 baseline + bootstrap + forward。
4. backend-full: 容器内非 root 全量 discover(canonical
   `HGS_PUBLIC_BASE_URL`, 临时 skill/avatar 目录, Redis DB15 串行)。
5. web: 四件套。
6. build: production build(互斥复核 + build-active 标记)。
7. worker: 干净 venv 导入检查。

汇总状态只在全部阶段完成后才 PASS; 任何阶段 BLOCKED/FAIL 即整体非零。
有意 skip 用 `--allow-skip <完整用例id>` 逐项声明并能在结果里对上, 整模块
白名单不生效。release 不部署、不推送、不打 tag — 部署见 docs/DEPLOYMENT.md。

## 8. skip / xfail / 失败判定

- 空选择(0 个用例被执行)、模块导入失败、失败/错误/意外成功、**未许可
  的 skip** 一律非 PASS; 缺环境、缺样本、安装超时记 BLOCKED 而不是 FAIL,
  但都不得记为通过。
- 有意 skip 必须是测试文件内显式声明的领域理由(如父类已跑的重复用例),
  门禁侧用 `--allow-skip` 逐用例声明; 依赖"库里恰好有旧样本"的 skip 属
  夹具缺陷, 修夹具而不是加白名单。
- xfail 必须有依据且不得覆盖本批缺陷；默认非通过，许可需 `--allow-xfail <完整用例id>`，结果逐项记录。CI host 经 `local/unittest_gate.py` 使用同一结果判定。
- 容器步骤通过 `local/run_step.sh` 管理自有进程组和远程 deadline；宿主也终止并等待自己的进程组。停止未确认时保留资源并以 Redis 隔离标记阻止后续测试，核实后才解除。
