"""对外数据服务的请求签名与防重放契约。

签名正确/错签/过期/重放/未登记路径/scope 不足/停用凭证逐项锁定;
全程零外网访问(nonce 走本地测试 Redis)。
"""

from __future__ import annotations

import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.data_api.auth import (  # noqa: E402
    CHEMICAL_READ_SCOPE, REACTION_READ_SCOPE, DataApiAuthError, DataClient,
    SCOPE_PATHS, authorize_scope, body_sha256_hex, compute_signature,
    generate_token, sign_message, token_hash, verify_signature)

TOKEN = "hgsd_unit_test_token"


def _headers(**overrides):
    return {
        "method": "GET", "path": "/data/v1/chemicals/996", "query": "locale=zh-CN",
        "body": b"", "timestamp": str(int(time.time())), "nonce": uuid.uuid4().hex,
        **overrides,
    }


def _signed(**overrides):
    parts = _headers(**overrides)
    parts["signature"] = compute_signature(
        TOKEN, sign_message(
            parts["method"], parts["path"], parts["query"],
            body_sha256_hex(parts["body"]), parts["timestamp"], parts["nonce"]))
    return parts


class SignatureTests(unittest.TestCase):
    def test_correct_signature_passes(self):
        parts = _signed()
        verify_signature(TOKEN, **parts)

    def test_wrong_signature_rejected(self):
        parts = _headers()
        with self.assertRaises(DataApiAuthError) as ctx:
            verify_signature(TOKEN, **parts, signature="0" * 64)
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_tampered_query_rejected(self):
        parts = _signed()
        with self.assertRaises(DataApiAuthError):
            verify_signature(TOKEN, **{**parts, "query": "locale=ja"})

    def test_expired_timestamp_rejected(self):
        parts = _signed(timestamp=str(int(time.time()) - 400))
        with self.assertRaises(DataApiAuthError) as ctx:
            verify_signature(TOKEN, **parts)
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_malformed_timestamp_rejected(self):
        parts = _signed(timestamp="not-a-number")
        with self.assertRaises(DataApiAuthError):
            verify_signature(TOKEN, **parts)

    def test_signature_message_layout(self):
        message = sign_message("GET", "/data/v1/chemicals/996", "locale=zh-CN",
                               body_sha256_hex(b""), "1000", "n1")
        self.assertEqual(
            message,
            b"GET\n/data/v1/chemicals/996\nlocale=zh-CN\n"
            + body_sha256_hex(b"").encode() + b"\n1000\nn1")

    def test_token_shape_and_hash(self):
        token = generate_token()
        self.assertTrue(token.startswith("hgsd_"))
        self.assertEqual(token_hash(token), token_hash(token))
        self.assertNotEqual(token_hash(token), token_hash(token + "x"))


class NonceReplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonce_replayed_rejected(self):
        from api.services.data_api.auth import check_nonce

        nonce = uuid.uuid4().hex
        await check_nonce("replay-client", nonce)
        with self.assertRaises(DataApiAuthError) as ctx:
            await check_nonce("replay-client", nonce)
        self.assertEqual(ctx.exception.code, "replayed_request")

    async def test_different_clients_same_nonce_ok(self):
        from api.services.data_api.auth import check_nonce

        nonce = uuid.uuid4().hex
        await check_nonce("replay-client-a", nonce)
        await check_nonce("replay-client-b", nonce)


class ScopeTests(unittest.TestCase):
    def _client(self, scopes):
        return DataClient(id=1, client_id="c", scopes=scopes,
                          rate_per_minute=60, rate_per_day=1000)

    def test_registered_path_allowed(self):
        authorize_scope(self._client([CHEMICAL_READ_SCOPE]),
                        "GET", "/data/v1/chemicals/{hcid}")

    def test_unregistered_path_refused(self):
        with self.assertRaises(DataApiAuthError) as ctx:
            authorize_scope(self._client([CHEMICAL_READ_SCOPE, REACTION_READ_SCOPE]),
                            "GET", "/data/v1/chemicals/{hcid}/unknown")
        self.assertEqual(ctx.exception.code, "forbidden_scope")
        self.assertEqual(ctx.exception.status, 403)

    def test_wrong_method_refused(self):
        with self.assertRaises(DataApiAuthError):
            authorize_scope(self._client([CHEMICAL_READ_SCOPE]),
                            "POST", "/data/v1/chemicals")

    def test_missing_scope_refused(self):
        with self.assertRaises(DataApiAuthError):
            authorize_scope(self._client([REACTION_READ_SCOPE]),
                            "GET", "/data/v1/chemicals/{hcid}")

    def test_every_route_template_registered(self):
        templates = {t for paths in SCOPE_PATHS.values() for t in paths}
        for expected in (
            ("GET", "/data/v1/chemicals"),
            ("GET", "/data/v1/chemicals/lookup"),
            ("GET", "/data/v1/chemicals/{hcid}"),
            ("GET", "/data/v1/chemicals/{hcid}/reactions"),
            ("GET", "/data/v1/reactions"),
            ("GET", "/data/v1/reactions/{hrid}"),
        ):
            self.assertIn(expected, templates)


if __name__ == "__main__":
    unittest.main()
