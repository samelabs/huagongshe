"""共享 TestClient fixture(单进程单 lifespan)。

背景(0912): app lifespan 内 mcp_session_lifespan 启动
StreamableHTTPSessionManager.run() — 该 manager 每实例只能 run 一次。
两个测试模块各起新 TestClient(app) 会第二次进入 lifespan → RuntimeError。
MCP 与 app startup 生产逻辑零改动; 测试侧统一从本模块取共享 client,
首个使用方启动, 进程内所有 workapi 测试复用; 不 skip、不拆进程。
"""
from __future__ import annotations

import threading

_client = None
_lock = threading.Lock()


def get_shared_client():
    """进程级单例 TestClient。调用方不负责 __exit__ — 进程退出时随解释器终结。"""
    global _client
    with _lock:
        if _client is None:
            from fastapi.testclient import TestClient
            from api.main import app
            cm = TestClient(app)
            _client = cm.__enter__()
    return _client
