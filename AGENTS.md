# huagongshe 开发纪律

## 分支对齐与基座

事故样本：主页按钮修复提交在 `batch/profile-visual-btn-closeout`，下一批次却从 `origin/main` 起头，用户在本地实例看到未修复状态（丢包）；同日发现本地 `main` 落后 10 个提交未同步、cwd 遗留两次造成假测试失败。

- **切新批次分支前必须 `git branch -vv` 清点全部本地分支**。凡有未合入 `origin/main` 且未推送的在飞批次线，新批次必须叠在其上（`git checkout -b <new> <在飞批次>`）或先把在飞线合入再动；直接从 `origin/main` 起头 = 丢包。
- **交付报告必须附 containment 证明**：对每条本地分支跑 `git merge-base --is-ancestor <branch> HEAD`（或证明已并入 `origin/main`），逐条列出去向表；答不上任何一条的去向，不得报告完成。
- **开工即同步基座**：`git fetch origin` 后顺手 fast-forward 本地 main：`git fetch origin main:main`；盘点表里不留 behind 的陈旧指针。

## 命令与检查纪律

- **仓库级命令一律从仓库根执行**；检查入口 `python3 local/check.py` 在仓库树内任意位置会自动回根，在别的树上直接拒绝。`cd web` 之后必须先回根；`npm --prefix web …` 只从仓库根跑（从 `web/` 内会拼出 `web/web`）。
- **测试唯一权威手册是 `docs/TESTING.md`**：分级、环境、隔离、退出码、skip 政策以它为准；本文件只保留强制摘要。
- **检查入口**：`python3 local/check.py {preflight|web|backend --tests …|worker|release}`。退出码 0=PASS / 1=FAIL / 2=BLOCKED / 3=用法错误；空选择、未知模块、未许可 skip 都不得记为通过。
- **后端测试经 `check.py backend --tests tests.<模块>…` 跑**：自动建每 run 专有测试库、非 root `tester`、非 root 下执行，结束后只清理本 run 资源；不再手写 docker exec 长命令、不再共用 `test_hgs`。
- **测试结果 gate 提交**：`git commit` 不许盲排在测试命令之后；测试非绿先停在 commit 前，分辨真失败与环境假失败。
- 推送前本地等价检查：`python3 local/check.py web`；后端改动跑 `check.py backend --tests tests.<涉及模块>…`（改到通知/关注链路加 `tests.test_activity_feed_notes`；改样式/设计令牌加 `tests.test_ui_token_contract tests.test_style_ratchet`）。

## 本地环境速查

- 栈：`local/stack`（docker compose，db 55433 / redis 56380 / api 8000，全部 127.0.0.1）；前端唯一入口 `local/dev.sh`（next dev 3000 + uploads 3010，与 production build 互斥，见 docs/TESTING.md）。
- api 容器以只读挂载跑工作树、无 `--reload`：**改 api/ 代码后需 `docker restart hgs_local_api` 生效**（容器内新起的测试进程读的是挂载文件，无需重启）。
- 迁移由 `check.py` 在 run 专有库上执行（原生 scheme URL、不带 `test_sentinel`，libpq 不认 sentinel 参数）；手工跑迁移同样从仓库根 `python3 scripts/migrate.py "postgresql://…"`。
- 演示账号：`hgs_demo` / `hgs_peer` / `hgs_admin`，口令在 `local/stack/.env.local` 的 `SEED_HGS_*`。
