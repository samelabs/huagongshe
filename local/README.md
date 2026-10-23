# 本地开发环境（唯一入口）

> 本目录是本地开发环境的唯一规范形态。**web dev 不进 docker**（HMR/文件
> 监听走宿主机），docker 只放有状态服务（db/redis/api）。

## 目录

| 路径 | 内容 |
|---|---|
| `stack/` | docker compose 栈（db=pg16+rdkit 55433 · redis 56380 · api 8000，全部 127.0.0.1），照搬 CI integration job |
| `stack/uploads_server.py` | `/uploads` 静态服务（127.0.0.1:3010）——生产由 nginx 承担，本地由它承担；文件读 `../uploads` |
| `uploads/` | 上传文件落盘（gitignore；与 api 容器 `HGS_AVATAR_ROOT` 同一 bind 目录，上传即落盘） |
| `dev.sh` | **前端开发唯一入口**：3010 静态服务 + `next dev`（3000，绑 0.0.0.0） |

## 起栈（首次）

```bash
cd local/stack
cp .env.local.example .env.local   # 模板已入库；改掉两处 change-me 即可
docker compose --env-file .env.local up -d --build      # db/redis/api
./seed.py 2>/dev/null || true                          # 可选：演示数据
```

## 日常开发

```bash
local/dev.sh          # http://localhost:3000
```

手机真机：与电脑同网段访问 `http://<电脑IP>:3000`。`web/next.config.ts` 的
`allowedDevOrigins` 会在 dev 启动时自动放行本机局域网地址（生产构建恒为空
名单）；`/uploads/*` 由 dev-only rewrite 转 3010 静态服务（生产零配置）。
dev 与 production build 在同一 checkout 上互斥（标记 + 端口守卫，见
docs/TESTING.md）。

## 检查入口

```bash
python3 local/check.py preflight                # 只读环境盘点
python3 local/check.py web                      # 前端四件套(不 build)
python3 local/check.py backend --tests tests.<模块> …   # 后端最小模块集
python3 local/check.py worker                   # 干净 venv worker 检查
python3 local/check.py release --dry-run        # 发布门禁计划
```

每 run 自动建专有测试库/临时目录并只清理本 run 资源; 手册见
`docs/TESTING.md`(权威), 栈细节见 `stack/README.md`。

## 端口清单（历史漂移 3102/3103/3110/8009 全部废弃）

| 端口 | 服务 | 绑定 |
|---|---|---|
| 3000 | next dev（唯一前端入口） | 0.0.0.0（供手机） |
| 3010 | /uploads 静态服务 | 127.0.0.1 |
| 8000 | FastAPI（compose api） | 127.0.0.1 |
| 55433 / 56380 | postgres / redis（compose） | 127.0.0.1 |
