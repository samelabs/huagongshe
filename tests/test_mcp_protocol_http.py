"""MCP wire-contract tests for the real Streamable HTTP transport.

This deliberately does not call build_mcp_server().list_tools()/call_tool()
directly. The SDK client performs initialize, tools/list and tools/call over
the ASGI /mcp endpoint using the same stateless HTTP configuration as HGS.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://protocol:protocol@127.0.0.1:5432/unused",
)

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from api.mcp_server import build_mcp_server


class McpStreamableHttpProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_list_and_call_over_mcp_http(self):
        server = build_mcp_server()
        app = server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False
            ),
            host="0.0.0.0",
        )

        async with server.session_manager.run():
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app),
                base_url="http://testserver",
            ) as http:
                transport = streamable_http_client(
                    "http://testserver/mcp",
                    http_client=http,
                    terminate_on_close=False,
                )
                # legacy mode forces the initialize handshake instead of the
                # SDK's newer server/discover probe.
                async with Client(transport, mode="legacy") as client:
                    self.assertEqual(client.session.server_info.name, "huagongshe-aichem")
                    # 显示名不带协议后缀(客户端 UI 自带 MCP 语境); 机器标识 name 不变
                    self.assertEqual(client.session.server_info.title, "HGS AIchem")
                    self.assertEqual(client.session.server_info.version, server.version)

                    listed = await client.list_tools(cache_mode="refresh")
                    names = {tool.name for tool in listed.tools}
                    self.assertEqual(len(names), 13)
                    self.assertIn("get_chemical", names)
                    self.assertIn("create_reaction", names)

                    wire_tools = {tool.name: tool for tool in listed.tools}
                    self.assertFalse(
                        wire_tools["search_chemistry_data"].annotations.read_only_hint
                    )
                    self.assertTrue(
                        wire_tools["get_reaction"].annotations.read_only_hint
                    )
                    self.assertTrue(
                        wire_tools["create_reaction"].annotations.idempotent_hint
                    )
                    self.assertEqual(
                        (wire_tools["get_chemical"].meta or {}).get("securitySchemes"),
                        [{"type": "noauth"}],
                    )
                    self.assertEqual(
                        (wire_tools["create_reaction"].meta or {}).get("securitySchemes"),
                        [{"type": "oauth2", "scopes": ["reaction:write"]}],
                    )

                    protected = await client.call_tool("list_my_reactions", {})
                    self.assertTrue(protected.is_error)
                    protected_meta = getattr(protected, "meta", None) or {}
                    challenge = protected_meta.get("mcp/www_authenticate") or []
                    self.assertTrue(challenge)
                    self.assertIn("oauth-protected-resource", challenge[0])
                    self.assertIn('scope="read"', challenge[0])

                    # Invalid ID is rejected before any DB access. This proves
                    # a real tools/call round-trip without coupling this wire
                    # contract test to PostgreSQL or Redis. 后越界值在
                    # 入参 schema 校验即拒绝(pydantic 消息), 不再进入工具体
                    # 的运行时 ToolError —— 两种文案都算"入参被拒"。
                    result = await client.call_tool(
                        "get_chemical", {"chemical_id": 0, "enrich": "core"}
                    )
                    self.assertTrue(result.is_error)
                    text = str(result.content)
                    self.assertTrue(
                        "chemical_id is out of range" in text
                        or "Input should be greater than or equal to 1" in text,
                        f"unexpected rejection text: {text}")


if __name__ == "__main__":
    unittest.main()
