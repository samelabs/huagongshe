"""反应录入表单规则的前后端对账。

前端提交前校验的唯一规则来源是 web/lib/reactionRules.ts；后端权威是
api/schemas/reactions.py 的 pydantic 约束。两边各写一份必然漂移，
本契约逐项对账：数值范围、长度上限、开闭区间、枚举、来源配对表、
DOI 正则 —— 任一侧改动而另一侧未跟，此处即红。
"""

from __future__ import annotations

import re
import sys
import typing
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.chemistry import DOI_RE
from api.schemas.reactions import ParticipantBody, ReactionBody

RULES_PATH = Path(__file__).resolve().parents[1] / "web" / "lib" / "reactionRules.ts"


def _rules_source() -> str:
    return RULES_PATH.read_text(encoding="utf-8")


def _number(source: str, key: str) -> int:
    match = re.search(rf"\b{key}:\s*(-?\d+)", source)
    assert match, f"reactionRules.ts 缺少数值常量 {key}"
    return int(match.group(1))


def _list(source: str, key: str) -> list[str]:
    match = re.search(rf"\b{key}:\s*\[([^\]]*)\]", source)
    assert match, f"reactionRules.ts 缺少数组常量 {key}"
    return re.findall(r'"([^"]+)"', match.group(1))


def _bound(field, attr: str):
    for meta in field.metadata:
        value = getattr(meta, attr, None)
        if value is not None:
            return value
    return None


class ReactionRulesContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _rules_source()
        cls.p = ParticipantBody.model_fields
        cls.r = ReactionBody.model_fields

    def test_participant_count_bounds(self):
        field = self.r["participants"]
        self.assertEqual(_number(self.src, "participantsMin"), _bound(field, "min_length"))
        self.assertEqual(_number(self.src, "participantsMax"), _bound(field, "max_length"))

    def test_occurrence_count_integer_range(self):
        field = self.p["occurrence_count"]
        self.assertEqual(_number(self.src, "occurrenceCountMin"), _bound(field, "ge"))
        self.assertEqual(_number(self.src, "occurrenceCountMax"), _bound(field, "le"))

    def test_non_negative_fields_share_zero_floor(self):
        for name in ("amount_value", "equivalents", "concentration_value"):
            self.assertEqual(_number(self.src, "nonNegativeMin"),
                             _bound(self.p[name], "ge"), name)

    def test_yield_range(self):
        field = self.p["yield_percent"]
        self.assertEqual(_number(self.src, "yieldMin"), _bound(field, "ge"))
        self.assertEqual(_number(self.src, "yieldMax"), _bound(field, "le"))

    def test_exclusive_minimums(self):
        self.assertEqual(_number(self.src, "durationExclusiveMin"), _bound(self.r["duration_value"], "gt"))
        self.assertEqual(_number(self.src, "pressureExclusiveMin"), _bound(self.r["pressure_value"], "gt"))

    def test_ph_range(self):
        field = self.r["ph"]
        self.assertEqual(_number(self.src, "phMin"), _bound(field, "ge"))
        self.assertEqual(_number(self.src, "phMax"), _bound(field, "le"))

    def test_length_limits(self):
        pairs = [
            ("smilesMaxLength", ("smiles", self.p)),
            ("amountUnitMaxLength", ("amount_unit", self.p)),
            ("atmosphereMaxLength", ("atmosphere", self.r)),
            ("doiMaxLength", ("doi", self.r)),
            ("patentMaxLength", ("patent", self.r)),
            ("sourceUrlMaxLength", ("source_url", self.r)),
            ("sourceCitationMaxLength", ("source_citation", self.r)),
            ("procedureMaxLength", ("procedure_details", self.r)),
        ]
        for key, (name, fields) in pairs:
            self.assertEqual(_number(self.src, key), _bound(fields[name], "max_length"), name)
        for name in ("conditions_detail", "workup_details", "safety_notes", "note"):
            self.assertEqual(_number(self.src, "textAreaMaxLength"),
                             _bound(self.r[name], "max_length"), name)

    def test_unit_enums(self):
        def literal_strings(annotation) -> list[str]:
            out: list[str] = []
            stack = [annotation]
            while stack:
                node = stack.pop()
                if node is type(None):
                    continue
                args = typing.get_args(node)
                if not args:
                    continue
                if all(isinstance(arg, str) for arg in args):
                    out.extend(args)
                else:
                    stack.extend(args)
            return sorted(out)

        self.assertEqual(_list(self.src, "temperatureUnits"),
                         literal_strings(self.r["temperature_unit"].annotation))
        self.assertEqual(sorted(_list(self.src, "durationUnits")),
                         literal_strings(self.r["duration_unit"].annotation))

    def test_doi_pattern_matches_backend(self):
        match = re.search(r'doiPattern:\s*"((?:[^"\\]|\\.)*)"', self.src)
        assert match, "reactionRules.ts 缺少 doiPattern"
        frontend = re.compile(match.group(1).replace("\\\\", "\\"))
        self.assertEqual(frontend.pattern, DOI_RE.pattern)

    def test_source_url_schemes(self):
        self.assertEqual(_list(self.src, "sourceUrlSchemes"), ["http://", "https://"])

    def test_source_type_required_field_map(self):
        block = re.search(
            r"requiredSourceField:\s*\{(.*?)\}\s*as", self.src, re.S)
        assert block, "reactionRules.ts 缺少 requiredSourceField"
        frontend = dict(re.findall(r'(\w+):\s*"(\w+)"', block.group(1)))
        schema = Path(__file__).resolve().parents[1] / "api" / "schemas" / "reactions.py"
        backend_src = schema.read_text(encoding="utf-8")
        backend_block = re.search(r"requirements\s*=\s*\{(.*?)\}", backend_src, re.S)
        assert backend_block, "schema 缺少 requirements 配对表"
        # 后端按类型查已填值(self.xxx), 前端按类型查必填字段名 —— 两张表
        # 的键与指向的字段必须一致
        backend = dict(re.findall(r'"(\w+)":\s*self\.(\w+)', backend_block.group(1)))
        self.assertEqual(frontend, backend)


if __name__ == "__main__":
    unittest.main()
