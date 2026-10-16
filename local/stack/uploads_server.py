#!/usr/bin/env python3
"""uploads_server — 本地 dev 的 /uploads 静态服务（127.0.0.1:3010）。

生产由 nginx 承担 /uploads 静态文件；本地 dev 由本进程承担同一 URL 形态：
web 的 next.config（仅 development）把 /uploads/* rewrite 到本进程，
文件来自 local/uploads —— 与 hgs_local_api 容器的 HGS_AVATAR_ROOT 是同一
bind 目录，上传即落盘、即时可见。

仅本地开发用；stdlib 实现，无第三方依赖。由 local/dev.sh 统一拉起。
"""
import sys
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 3010
ROOT = Path(__file__).resolve().parent.parent / "uploads"


class UploadsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("cache-control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 静态文件访问不刷屏；错误仍走异常路径


def main() -> int:
    if not ROOT.is_dir():
        print(f"[uploads_server] 缺少上传目录 {ROOT}（mkdir 后再启动）", file=sys.stderr)
        return 1
    ThreadingHTTPServer(("127.0.0.1", PORT), UploadsHandler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
