"""字段校验错误契约。

请求体校验失败统一返回 {message, kind} 且带字段名, 前端按字段定位展示;
个人网址裸域名自动补 https://。数值边界错误的方向文案必须与值的实际
偏离方向一致（大于下限/超出上限），不得按校验类型名字面直译。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from api.main import _validation_error_response
from api.schemas.users import ProfileBody


class ProbeBody(BaseModel):
    count: int
    code: str = Field(pattern=r"^[A-Z]{3}$")
    tags: list[str] = Field(min_length=2, max_length=4)


def _app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, _validation_error_response)

    @app.patch("/users/me")
    async def update_profile(body: ProfileBody):
        return {"website": body.website}

    @app.get("/probe")
    async def probe(page: int = Query(1, ge=1, le=50)):
        return {"page": page}

    @app.post("/probe/body")
    async def probe_body(body: ProbeBody):
        return {"ok": True}

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
        r = self.client.patch("/users/me", json={
            "display_name": "x", "email": "a@b.co", "website": "ftp://x.y"})
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertEqual(payload["field"], "website")


class NumericBoundaryDirectionTests(unittest.TestCase):
    """数值边界文案方向：值太大→超出上限，值太小→低于下限。"""

    def setUp(self):
        self.client = TestClient(_app())

    def test_value_above_upper_limit_reports_over(self):
        r = self.client.get("/probe", params={"page": 51})
        self.assertEqual(r.status_code, 422)
        self.assertIn("超出上限", r.json()["message"])

    def test_value_below_lower_limit_reports_under(self):
        r = self.client.get("/probe", params={"page": 0})
        self.assertEqual(r.status_code, 422)
        self.assertIn("低于下限", r.json()["message"])


class ValidationTypeMappingTests(unittest.TestCase):
    """校验类型 → 中文文案映射：英文原文不得直出。"""

    def setUp(self):
        self.client = TestClient(_app())

    def _message(self, **kwargs) -> str:
        r = self.client.post("/probe/body", json=kwargs)
        self.assertEqual(r.status_code, 422)
        return r.json()["message"]

    def test_float_into_int_field_maps_to_integer_hint(self):
        message = self._message(count=1.5, code="ABC", tags=["a", "b"])
        self.assertIn("必须是整数", message)

    def test_pattern_mismatch_maps_to_format_hint(self):
        message = self._message(count=1, code="abc", tags=["a", "b"])
        self.assertIn("格式不正确", message)

    def test_list_too_short_maps_to_count_hint(self):
        message = self._message(count=1, code="ABC", tags=["a"])
        self.assertIn("数量不足", message)

    def test_list_too_long_maps_to_count_hint(self):
        message = self._message(count=1, code="ABC", tags=["a", "b", "c", "d", "e"])
        self.assertIn("数量超出", message)

    def test_no_raw_english_leaks(self):
        for kwargs in (
            {"count": 1.5, "code": "ABC", "tags": ["a", "b"]},
            {"count": 1, "code": "abc", "tags": ["a", "b"]},
            {"count": 1, "code": "ABC", "tags": ["a"]},
            {"count": 1, "code": "ABC", "tags": ["a", "b", "c", "d", "e"]},
        ):
            message = self._message(**kwargs)
            self.assertNotIn("Input should be", message)
            self.assertNotIn("List should have", message)
            self.assertNotIn("String should match", message)


if __name__ == "__main__":
    unittest.main()
