# 本地开发环境（唯一入口）

> 2026-10-16 收口：此前 dev 端口多次漂移（3102→3110）且 compose 栈躺在
> `.rc-acceptance` 草稿目录，本目录是收口后的唯一规范形态。**web dev 不进
> docker**（HMR/文件监听走宿主机），docker 只放有状态服务（db/redis/api）。

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

## 端口清单（历史漂移 3102/3103/3110/8009 全部废弃）

| 端口 | 服务 | 绑定 |
|---|---|---|
| 3000 | next dev（唯一前端入口） | 0.0.0.0（供手机） |
| 3010 | /uploads 静态服务 | 127.0.0.1 |
| 8000 | FastAPI（compose api） | 127.0.0.1 |
| 55433 / 56380 | postgres / redis（compose） | 127.0.0.1 |

栈的详细说明（镜像构成、测试库、容器内跑全套测试）见 `stack/README.md`。
