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
#
# 产物互斥：next dev 与 production build 共用 web/.next，并发互相破坏。
# 启动前检查 local/check.py 的 build-active 标记，运行期持有 dev-active
# 标记（python3 local/check.py 的 release build 阶段据此拒绝覆盖）。
set -euo pipefail
cd "$(dirname "$0")/.."

DEV_MARKER="local/.dev-active.json"
BUILD_MARKER="local/.check-runs/build-active.json"

pid_alive() { kill -0 "$1" 2>/dev/null; }

# production build 正在跑则不启动 dev（读到半成品产物）
if [ -f "$BUILD_MARKER" ]; then
  bpid=$(python3 -c "import json;print(json.load(open('$BUILD_MARKER')).get('pid',0))" 2>/dev/null || echo 0)
  if [ "$bpid" -gt 0 ] && pid_alive "$bpid"; then
    echo "dev.sh: production build 正在运行(pid $bpid)，此时启动 dev 会读到半成品产物；稍后再试。" >&2
    exit 1
  fi
  rm -f "$BUILD_MARKER"   # 死进程残留标记，安全清理
fi

python3 - "$DEV_MARKER" "$$" <<'PY'
import json, os, sys, time
path, pid = sys.argv[1], int(sys.argv[2])
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as fh:
    json.dump({"kind": "dev", "pid": pid,
               "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, fh)
PY
clean_marker() { rm -f "$DEV_MARKER"; }
trap clean_marker EXIT

python3 local/stack/uploads_server.py &
UPLOADS_PID=$!

cd web
npm run dev &
DEV_PID=$!
cd ..

cleanup() {
  kill "$DEV_PID" "$UPLOADS_PID" 2>/dev/null || true
  wait "$DEV_PID" "$UPLOADS_PID" 2>/dev/null || true
  clean_marker
}
trap cleanup EXIT INT TERM

# 任一子进程退出即整体收摊（macOS bash 3.2 无 wait -n，秒级轮询替代）
while kill -0 "$DEV_PID" 2>/dev/null && kill -0 "$UPLOADS_PID" 2>/dev/null; do
  sleep 1
done
cleanup
