"""字段校验错误契约。

请求体校验失败统一返回 {message, kind} 且带字段名, 前端按字段定位展示;
个人网址裸域名自动补 https://。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.main import _validation_error_response
from api.schemas.users import ProfileBody


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(__import__("fastapi.exceptions", fromlist=["RequestValidationError"]).RequestValidationError,
                              _validation_error_response)

    @app.patch("/users/me")
    async def update_profile(body: ProfileBody):
        return {"website": body.website}

    return app


class FieldValidationContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_app())

    def test_invalid_website_returns_field_error(self):
        r = self.client.patch("/users/me", json={
            "display_name": "小明", "email": "a@b.co", "website": "not a url"})
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertEqual(payload["field"], "website")
        self.assertIn("个人主页", payload["message"])

    def test_missing_required_field_names_the_field(self):
        r = self.client.patch("/users/me", json={"email": "a@b.co"})
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertEqual(payload["field"], "display_name")
        self.assertIn("缺少必填字段", payload["message"])

    def test_oversized_field_reports_length(self):
        r = self.client.patch("/users/me", json={
            "display_name": "小明", "email": "a@b.co",
            "bio": "长" * 501})
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["field"], "bio")
        self.assertIn("长度上限", payload["message"])

    def test_bare_domain_autocompletes_https(self):
        r = self.client.patch("/users/me", json={
            "display_name": "小明", "email": "a@b.co",
            "website": "example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["website"], "https://example.com")

    def test_explicit_scheme_preserved(self):
        r = self.client.patch("/users/me", json={
            "display_name": "小明", "email": "a@b.co",
            "website": "http://example.com/x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["website"], "http://example.com/x")

    def test_model_level_error_still_carries_kind(self):
        from fastapi.exceptions import RequestValidationError

        try:
            ProfileBody(display_name="x", email="a@b.co", website="ftp://x.y")
        except Exception as exc:  # pydantic ValidationError
            validation = RequestValidationError(exc.errors())
            response = _validation_error_response(None, validation)
            import json as _json
            content = _json.loads(response.body)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(content["kind"], "invalid_field")
            self.assertEqual(content["field"], "website")
        else:
            self.fail("应抛出校验错误")


if __name__ == "__main__":
    unittest.main()
