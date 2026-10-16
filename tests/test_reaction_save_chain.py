"""反应保存链路: 从请求体校验到结构校验的错误契约。

逐场景锁: 最小合法反应、多参与物、缺产物、非法 SMILES、重复参与物、
超长文本、可见性取值、来源配对 — 请求体校验失败统一 {message, kind}
并尽量带字段名; 结构校验失败保持业务 kind。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from api.main import _validation_error_response
from api.schemas.reactions import ReactionBody
from api.services.reactions import (
    ReactionValidationError, canonical_participants,
)


def _participant(role: str, smiles: str) -> dict:
    return {"role": role, "smiles": smiles, "eq": 1} if role != "SOLVENT" \
        else {"role": role, "smiles": smiles}


def _body(participants: list[dict], **overrides) -> dict:
    payload = {
        "visibility": "public",
        "participants": participants,
        "source_type": "self",
    }
    payload.update(overrides)
    return payload


class _NoDB:
    """canonical_participants 只用到 db 的身份查询; 简单场景传 None 即可
    (身份解析发生在 canonical 失败/重复检测之后不影响断言路径)。"""


class ReactionSchemaChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(_app_with_reactions())

    def test_minimum_valid_reaction(self):
        body = ReactionBody(**_body([
            _participant("REACTANT", "CCO"),
            _participant("PRODUCT", "CC(=O)OCC"),
        ]))
        self.assertEqual(len(body.participants), 2)

    def test_multi_participant_reaction(self):
        body = ReactionBody(**_body([
            _participant("REACTANT", "CCO"),
            _participant("REACTANT", "CC(=O)O"),
            _participant("REAGENT", "c1ccccc1"),
            _participant("CATALYST", "O=S(=O)(O)O"),
            _participant("SOLVENT", "O"),
            _participant("PRODUCT", "CC(=O)OCC"),
        ]))
        self.assertEqual(len(body.participants), 6)

    def test_missing_product_is_field_error(self):
        r = self.client.post("/reactions", json=_body([
            _participant("REACTANT", "CCO"),
            _participant("REACTANT", "CC(=O)O"),
        ]))
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertIn("至少需要一个反应物和一个产物", payload["message"])

    def test_invalid_smiles_is_business_kind(self):
        body = ReactionBody(**_body([
            {"role": "REACTANT", "smiles": "not-a-smiles", "eq": 1},
            {"role": "PRODUCT", "smiles": "CCO", "eq": 1},
        ]))
        with self.assertRaises(ReactionValidationError) as ctx:
            canonical_participants(body)
        self.assertEqual(ctx.exception.kind, "invalid_structure")

    def test_duplicate_participant_is_business_kind(self):
        body = ReactionBody(**_body([
            {"role": "REACTANT", "smiles": "CCO", "eq": 1},
            {"role": "REACTANT", "smiles": "OCC", "eq": 1},
            {"role": "PRODUCT", "smiles": "CC(=O)OCC", "eq": 1},
        ]))
        with self.assertRaises(ReactionValidationError) as ctx:
            canonical_participants(body)
        self.assertEqual(ctx.exception.kind, "duplicate_participant")

    def test_oversized_procedure_is_field_error(self):
        r = self.client.post("/reactions", json=_body(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            procedure_details="步" * 30001))
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertEqual(payload["field"], "procedure_details")

    def test_visibility_enum_rejected(self):
        r = self.client.post("/reactions", json=_body(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            visibility="friends"))
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["kind"], "invalid_field")

    def test_private_visibility_accepted(self):
        body = ReactionBody(**_body(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            visibility="private"))
        self.assertEqual(body.visibility, "private")

    def test_source_pairing_required(self):
        r = self.client.post("/reactions", json=_body(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            source_type="doi"))
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertIn("缺少对应的来源信息", payload["message"])

    def test_temperature_pairing_required(self):
        r = self.client.post("/reactions", json=_body(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            temperature_value=25.0))
        self.assertEqual(r.status_code, 422)
        self.assertIn("温度数值和单位必须同时填写", r.json()["message"])

    def test_yield_only_on_product(self):
        r = self.client.post("/reactions", json=_body([
            {"role": "REACTANT", "smiles": "CCO", "eq": 1, "yield_percent": 90},
            {"role": "PRODUCT", "smiles": "CCO", "eq": 1},
        ]))
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertIn("只有产物可以填写收率", payload["message"])


def _app_with_reactions() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, _validation_error_response)

    @app.post("/reactions")
    async def create_reaction(body: ReactionBody):
        return {"ok": True, "visibility": body.visibility}

    return app


if __name__ == "__main__":
    unittest.main()
