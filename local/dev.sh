#!/usr/bin/env bash
# dev.sh — 本地前端开发唯一入口：上传静态服务(3010) + next dev(3000)。
#
# 前置：local/stack/docker-compose.yml 的 api/db/redis 已起（见 local/README.md）。
# 手机真机：与电脑同网段访问 http://<电脑IP>:3000（dev 脚本绑 0.0.0.0，
# next.config 的 allowedDevOrigins 已放行本机局域网地址）。
set -euo pipefail
cd "$(dirname "$0")/.."

# 幂等：先停掉旧的上传静态服务再拉起
if lsof -tiTCP:3010 -sTCP:LISTEN >/dev/null 2>&1; then
  kill "$(lsof -tiTCP:3010 -sTCP:LISTEN)" 2>/dev/null || true
  sleep 0.3
fi
python3 local/stack/uploads_server.py &
UPLOADS_PID=$!
trap 'kill "$UPLOADS_PID" 2>/dev/null || true' EXIT

cd web
exec npm run dev
