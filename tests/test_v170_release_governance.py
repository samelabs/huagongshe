"""v1.7.0 release-candidate governance contract.

锁定本轮治理结论(全部走真实代码路径/文件结构, 非字符串堆砌):

- HGS 产品版本(仓库根 VERSION)= 1.7.0, 且 MCP serverInfo 读取同一来源
- HTTP API contract version(settings.api_version)不随产品版本走(1.0.0)
- 首页一级入口不再暴露 Agent API 与 AI Key; /api/agent-guide 与
  /me/settings/api-tokens 路由本身保留
- MCP Guide 页仍提供 AI Key 入口
- Plugin 包版本独立于产品版本(1.0.0), MCP target 指向生产 /mcp
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://governance:governance@127.0.0.1:5432/unused",
)

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class ProductVersionContract(unittest.TestCase):
    def test_version_is_1_7_0(self):
        value = (REPO / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(value, "1.7.0")

    def test_mcp_server_version_reads_the_same_source(self):
        from api import mcp_server

        self.assertEqual(mcp_server._release_version(), "1.7.0")

    def test_http_api_contract_version_unchanged(self):
        from api.core.config import settings

        self.assertEqual(settings.api_version, "1.0.0")

    def test_agent_guide_payload_still_reports_api_version(self):
        from api.agent import agent_guide

        class _StubDb:
            async def execute(self, *_a, **_k):
                class _R:
                    def scalar(self):
                        return None

                return _R()

        import asyncio

        payload = asyncio.run(agent_guide(authorization=None, actor=None, db=_StubDb()))
        self.assertEqual(payload["api_version"], "1.0.0")


class HomePageEntryContract(unittest.TestCase):
    """首页源码结构契约: MCP / Skills / Workbench / Plugin，AI Key 不单列。"""

    @classmethod
    def setUpClass(cls):
        cls.source = (WEB / "app" / "(site)" / "page.tsx").read_text(encoding="utf-8")

    def test_home_primary_entries(self):
        self.assertIn('"/mcp-guide"', self.source)
        self.assertIn('"/skills"', self.source)
        self.assertIn('"/aichem"', self.source)
        self.assertIn("entryPlugin", self.source)
        self.assertIn("#chatgpt-plugin", self.source)

    def test_agent_api_not_a_home_entry(self):
        self.assertNotIn('"/api/agent-guide"', self.source)
        self.assertNotIn("entryApi", self.source)

    def test_ai_key_not_a_home_entry(self):
        self.assertNotIn("/me/settings/api-tokens", self.source)
        self.assertNotIn("entryKey", self.source)


class CompatibilitySurfaceKept(unittest.TestCase):
    def test_agent_guide_route_still_registered(self):
        # api/main.py: app.include_router(agent_router, prefix="/api")。
        # 新版 FastAPI 把 include 后的 router 包成 _IncludedRouter,
        # 子路由 path 是 router 内路径, prefix 在 include_context 上。
        from api.main import app

        def registered_paths():
            for r in app.routes:
                if type(r).__name__ == "_IncludedRouter":
                    prefix = getattr(r.include_context, "prefix", "") or ""
                    for sub in r.original_router.routes:
                        yield prefix + getattr(sub, "path", "")
                else:
                    yield getattr(r, "path", "")

        self.assertIn("/api/agent-guide", list(registered_paths()))

    def test_ai_key_settings_route_still_exists(self):
        page = WEB / "app" / "(workbench)" / "me" / "settings" / "api-tokens" / "page.tsx"
        self.assertTrue(page.exists(), "AI Key settings 路由被误删")

    def test_mcp_guide_still_offers_ai_key_entry(self):
        source = (WEB / "app" / "(site)" / "mcp-guide" / "page.tsx").read_text(encoding="utf-8")
        self.assertIn("/me/settings/api-tokens", source)

    def test_locale_dictionaries_dropped_home_only_keys(self):
        for locale in ("zh-CN", "en", "ja", "ko", "de"):
            source = (WEB / "lib" / "i18n" / "locales" / f"{locale}.ts").read_text(encoding="utf-8")
            self.assertNotIn("entryApi", source, locale)
            self.assertNotIn("entryKey", source, locale)
            self.assertIn("entryPlugin", source, locale)
            self.assertIn("pluginStatus", source, locale)
            self.assertIn("languageSwitcher", source, locale)


class PluginDistributionBoundary(unittest.TestCase):
    """Plugin = 现有 MCP 的分发包装层, 版本轴与产品版本解耦。"""

    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_json(REPO / "plugins" / "huagongshe" / "plugin.json")
        cls.mcp = _load_json(REPO / "plugins" / "huagongshe" / "mcp.json")

    def test_plugin_package_version_is_independent(self):
        self.assertEqual(self.manifest["version"], "1.0.0")
        self.assertNotEqual(self.manifest["version"], (REPO / "VERSION").read_text(encoding="utf-8").strip())

    def test_plugin_targets_production_mcp_only(self):
        servers = self.mcp["mcpServers"]
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers["huagongshe"]["url"], "https://huagongshe.com/mcp")

    def test_plugin_ships_no_business_implementation(self):
        plugin_dir = REPO / "plugins" / "huagongshe"
        shipped = sorted(p.relative_to(plugin_dir).as_posix() for p in plugin_dir.rglob("*") if p.is_file())
        self.assertEqual(shipped, ["assets/icon.png", "mcp.json", "plugin.json"])


if __name__ == "__main__":
    unittest.main()
