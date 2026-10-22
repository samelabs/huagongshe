"""接近 ZIP 上限的技能包经 Web 与 MCP 两条通道都能进入应用校验。

上限唯一来源是 settings.skill_zip_max_bytes。传输层不得先于应用层拦截
合规尺寸的包: MCP Streamable HTTP 默认请求体 4 MiB 装不下 Base64 后的
技能包, mount_mcp 以同一 settings 推导请求体上限。回归锁两件事:
- Web REST 校验入口对接近 ZIP 上限的包返回的是解包总量语义
  (进入应用校验), 不是传输层/压缩包上限语义;
- MCP 传输层对 >4 MiB 且 ≤ 推导上限的请求体放行, 超过推导上限仍 413。
"""

from __future__ import annotations

import io
import json
import os
import unittest
import zipfile
from unittest.mock import patch

from api.core.config import settings


def _near_cap_zip() -> bytes:
    """结构合法、体积贴近上限的包: 多个 ≤2MB 的随机文件(避开单文件闸),
    解包总量 >10MB 触发总量闸; 随机数据不可压缩, zip 体积 ≈ 原始总量。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("SKILL.md", b"---\nname: big\ndescription: big\n---\nbody")
        for i in range(9):
            z.writestr(f"assets/blob{i}.bin", os.urandom(1150 * 1024))
    return buf.getvalue()


class SkillUploadReachValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_validate_reaches_archive_checks_near_cap(self):
        """接近 ZIP 上限的 multipart 包进入应用校验: 返回的是解包总量
        语义(应用层第 2 道闸), 不是压缩包上限语义, 更不是传输层拒绝。"""
        from fastapi import HTTPException
        from api import skills as skills_module
        from api.core.security import Actor

        raw = _near_cap_zip()
        self.assertGreater(len(raw), 4 * 1024 * 1024,
                           "样本必须超过 MCP 旧默认 4 MiB 才有回归意义")
        self.assertLessEqual(len(raw), settings.skill_zip_max_bytes)

        class _Upload:
            async def read(self, n: int = -1) -> bytes:
                return raw[:n] if n > 0 else raw

        actor = Actor(id=1, username="u", display_name="U",
                      email="u@t.example", role="member", avatar_path=None,
                      auth_kind="web")
        async def _no_limit(*_a, **_k):
            return None
        with patch.object(skills_module, "enforce_http", _no_limit):
            with self.assertRaises(HTTPException) as raised:
                await skills_module.validate_skill(file=_Upload(), actor=actor)
        detail = raised.exception.detail
        self.assertEqual(detail["kind"], "archive_limit")
        self.assertIn("解包后总量", detail["message"],
                      "必须进入解包总量校验(应用层), 而非压缩包上限或传输层")

    async def test_mcp_transport_admits_over_default_and_blocks_over_derived(self):
        """>4 MiB(旧默认拒收)且 ≤ 推导上限的请求体进入 MCP 协议处理;
        超过推导上限仍按 413 截断 —— 上限与 ZIP 上限同源推导。"""
        import httpx2
        from mcp.server.transport_security import TransportSecuritySettings
        from api.mcp_server import build_mcp_server, mcp_request_body_limit

        limit = mcp_request_body_limit(settings.skill_zip_max_bytes)
        self.assertGreaterEqual(
            limit, settings.skill_zip_max_bytes * 4 // 3,
            "请求体上限必须容纳 Base64(ZIP 上限)")

        server = build_mcp_server()
        app = server.streamable_http_app(
            streamable_http_path="/mcp",
            stateless_http=True,
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=False),
            max_request_body_size=limit,
            host="0.0.0.0",
        )
        # 未授权调用在工具层被拒即可证明过了传输层; 载荷取真实 Base64 尺寸段
        admitted = "A" * (5 * 1024 * 1024)
        blocked = "A" * (limit + 1024 * 1024)

        async with server.session_manager.run():
            transport = httpx2.ASGITransport(app=app)
            async with httpx2.AsyncClient(
                transport=transport, base_url="http://testserver",
            ) as http:
                r1 = await http.post("/mcp", content=json.dumps({
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "validate_skill",
                               "arguments": {"zip_base64": admitted}},
                }).encode(), headers={
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                })
                r2 = await http.post("/mcp", content=json.dumps({
                    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "validate_skill",
                               "arguments": {"zip_base64": blocked}},
                }).encode(), headers={
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                })
        self.assertNotEqual(r1.status_code, 413,
                            "5MiB 载荷须进入协议处理(旧默认 4MiB 会 413)")
        self.assertEqual(r2.status_code, 413,
                         "超过推导上限的载荷仍须在传输层截断")


if __name__ == "__main__":
    unittest.main()
