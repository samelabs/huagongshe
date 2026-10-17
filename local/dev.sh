#!/usr/bin/env bash
# dev.sh — 本地前端开发唯一入口：上传静态服务(3010) + next dev(3000)。
#
# 前置：local/stack/docker-compose.yml 的 api/db/redis 已起（见 local/README.md）。
# 手机真机：与电脑同网段访问 http://<电脑IP>:3000（dev 脚本绑 0.0.0.0，
# next.config 的 allowedDevOrigins 已放行本机局域网地址）。
#
# 进程模型：本脚本作为父进程保留生命周期，两个子进程由它拉起与回收；
# 不用 exec（exec 会替换掉本 shell，EXIT trap 永不执行，子进程残留），
# 也不按端口猎杀监听进程（可能误杀他人）。
set -euo pipefail
cd "$(dirname "$0")/.."

python3 local/stack/uploads_server.py &
UPLOADS_PID=$!

cd web
npm run dev &
DEV_PID=$!
cd ..

cleanup() {
  kill "$DEV_PID" "$UPLOADS_PID" 2>/dev/null || true
  wait "$DEV_PID" "$UPLOADS_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# 任一子进程退出即整体收摊（macOS bash 3.2 无 wait -n，秒级轮询替代）
while kill -0 "$DEV_PID" 2>/dev/null && kill -0 "$UPLOADS_PID" 2>/dev/null; do
  sleep 1
done
cleanup
