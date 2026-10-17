"""反应保存链路: 从请求体校验到结构校验的错误契约。

逐字段契约表: 每个可输入字段填错时, 锁定 (status, kind, field, 文案
方向) 四元组 —— 前端按 field 定位到具体输入, 文案方向与值的实际偏离
方向一致。参与物级错误(结构无法解析/同角色重复)由后端带出参与物行号,
前端据此定位到该行。
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
from api.reactions import _reaction_validation_http
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
        # 与真实 create 端点同一错误链: 请求体校验(422)之外, 结构校验
        # 错误经同一传输层映射(400/409, 带参与物行号字段路径)。
        try:
            canonical_participants(body)
        except ReactionValidationError as exc:
            raise _reaction_validation_http(exc) from exc
        return {"ok": True, "visibility": body.visibility}

    return app


class FieldContractTableTests(unittest.TestCase):
    """逐字段契约表: 字段 → (status, kind, field, 文案方向)。"""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(_app_with_reactions())

    def _post(self, participants, **overrides):
        return self.client.post("/reactions", json=_body(participants, **overrides))

    def test_invalid_smiles_carries_participant_position(self):
        r = self._post([
            {"role": "REACTANT", "smiles": "CCO", "eq": 1},
            {"role": "PRODUCT", "smiles": "not-a-smiles", "eq": 1},
        ])
        self.assertEqual(r.status_code, 400)
        payload = r.json()["detail"]
        self.assertEqual(payload["kind"], "invalid_structure")
        self.assertEqual(payload["field"], "participants.1.smiles")
        self.assertIn("第 2 个参与物", payload["message"])

    def test_duplicate_participant_carries_participant_position(self):
        r = self._post([
            {"role": "REACTANT", "smiles": "CCO", "eq": 1},
            {"role": "REACTANT", "smiles": "OCC", "eq": 1},
            {"role": "PRODUCT", "smiles": "CC(=O)OCC", "eq": 1},
        ])
        self.assertEqual(r.status_code, 409)
        payload = r.json()["detail"]
        self.assertEqual(payload["kind"], "duplicate_participant")
        self.assertEqual(payload["field"], "participants.1")
        self.assertIn("第 2 个参与物", payload["message"])

    def test_occurrence_float_is_integer_hint(self):
        r = self._post([
            {"role": "REACTANT", "smiles": "CCO", "occurrence_count": 1.5},
            {"role": "PRODUCT", "smiles": "CCO"},
        ])
        self.assertEqual(r.status_code, 422)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertEqual(payload["field"], "participants.0.occurrence_count")
        self.assertIn("必须是整数", payload["message"])

    def test_occurrence_above_max_reports_over(self):
        r = self._post([
            {"role": "REACTANT", "smiles": "CCO", "occurrence_count": 21},
            {"role": "PRODUCT", "smiles": "CCO"},
        ])
        payload = r.json()
        self.assertEqual(payload["field"], "participants.0.occurrence_count")
        self.assertIn("超出上限", payload["message"])

    def test_duration_zero_reports_under(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            duration_value=0, duration_unit="HOUR")
        payload = r.json()
        self.assertEqual(payload["field"], "duration_value")
        self.assertIn("低于下限", payload["message"])

    def test_ph_above_max_reports_over(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            ph=15)
        payload = r.json()
        self.assertEqual(payload["field"], "ph")
        self.assertIn("超出上限", payload["message"])

    def test_ph_below_min_reports_under(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            ph=-1)
        payload = r.json()
        self.assertEqual(payload["field"], "ph")
        self.assertIn("低于下限", payload["message"])

    def test_pressure_pairing_required(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            pressure_value=1.5)
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertIn("压力数值和单位必须同时填写", payload["message"])

    def test_pressure_zero_reports_under(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            pressure_value=0, pressure_unit="bar")
        payload = r.json()
        self.assertEqual(payload["field"], "pressure_value")
        self.assertIn("低于下限", payload["message"])

    def test_bad_doi_format(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            doi="not-a-doi")
        payload = r.json()
        self.assertEqual(payload["field"], "doi")
        self.assertIn("DOI 格式不正确", payload["message"])

    def test_source_url_scheme_rejected(self):
        r = self._post(
            [_participant("REACTANT", "CCO"), _participant("PRODUCT", "CCO")],
            source_type="url", source_url="ftp://example.com/x")
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertIn("http://", payload["message"])

    def test_single_participant_reports_count(self):
        r = self._post([_participant("REACTANT", "CCO")])
        payload = r.json()
        self.assertEqual(payload["kind"], "invalid_field")
        self.assertIn("数量不足", payload["message"])

    def test_negative_amount_reports_under(self):
        r = self._post([
            {"role": "REACTANT", "smiles": "CCO", "amount_value": -1, "amount_unit": "mmol"},
            {"role": "PRODUCT", "smiles": "CCO"},
        ])
        payload = r.json()
        self.assertEqual(payload["field"], "participants.0.amount_value")
        self.assertIn("低于下限", payload["message"])

    def test_yield_above_100_reports_over(self):
        r = self._post([
            {"role": "REACTANT", "smiles": "CCO"},
            {"role": "PRODUCT", "smiles": "CCO", "yield_percent": 120},
        ])
        payload = r.json()
        self.assertEqual(payload["field"], "participants.1.yield_percent")
        self.assertIn("超出上限", payload["message"])


class CreateConflictKindTests(unittest.TestCase):
    """身份冲突 409 形态: create 与 validate 同形带 kind。"""

    def test_create_identity_conflict_carries_kind(self):
        import asyncio
        from unittest.mock import patch

        from api.core.security import Actor
        from api.services.reactions import UnresolvedIdentityError
        import api.reactions as reactions_module
        from fastapi import HTTPException

        body = ReactionBody(**_body([
            _participant("REACTANT", "CCO"),
            _participant("PRODUCT", "CCO"),
        ]))
        actor = Actor(id=1, username="u", display_name="u", email="e",
                      role="member", avatar_path=None, auth_kind="session")

        async def conflict(*args, **kwargs):
            raise UnresolvedIdentityError("CONFLICT", "标识符与结构存在冲突")

        async def go():
            with patch.object(reactions_module, "create_reaction_service", conflict):
                await reactions_module.create_reaction(
                    body=body, idempotency_key=None, actor=actor, db=None)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(go())
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["kind"], "chemical_identity_conflict")
        self.assertIn("message", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
