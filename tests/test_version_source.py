"""v1.7.2 — 版本号单一来源契约: 仓库根 VERSION 文件。

/api/health 的 version、FastAPI app.version(settings.api_version)与 MCP
serverInfo.version 三者必须同源, 都等于 VERSION 内容。此前
api/core/config.py 硬编码 api_version="1.0.0", 与读 VERSION 的 MCP
serverInfo 漂移(health 1.0.0 vs MCP 1.7.1), 已改为同一来源。
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _version_file() -> str:
    return (REPO / "VERSION").read_text(encoding="utf-8").strip()


class SingleVersionSourceTests(unittest.TestCase):
    def test_version_file_shape(self):
        v = _version_file()
        self.assertTrue(v, "VERSION 文件为空")
        self.assertRegex(v, r"^\d+\.\d+\.\d+$", f"VERSION 必须是 X.Y.Z: {v!r}")

    def test_settings_api_version_reads_version_file(self):
        from api.core.config import settings
        self.assertEqual(settings.api_version, _version_file(),
                         "api_version 必须读 VERSION 文件, 不得硬编码第二份")

    def test_fastapi_app_version_equals_version_file(self):
        from api.main import app
        self.assertEqual(app.version, _version_file())

    def test_health_endpoint_returns_version_file(self):
        from api.main import health
        self.assertEqual(asyncio.run(health()),
                         {"status": "ok", "version": _version_file()})

    def test_mcp_server_info_equals_version_file(self):
        from api.mcp_server import build_mcp_server
        self.assertEqual(build_mcp_server().version, _version_file())


if __name__ == "__main__":
    unittest.main()
