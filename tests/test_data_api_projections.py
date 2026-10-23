"""对外数据服务的投影与详情页字段一致性(真实数据样本比对)。

样本为公开化合物 HCID 996 / 80077 的详情响应(zh-CN 与 ja 各一份),
取自线上只读快照, 断言投影输出的分区与字段与详情页同一范式:
分区同名、字段只出现一次、标题按页面取名规则、单位保留。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.services.data_api.projections import (  # noqa: E402
    project_chemical, project_reaction, resolve_title)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SITE = "https://huagongshe.com"

SAMPLES = [
    ("996", "zh-CN"), ("996", "ja"),
    ("80077", "zh-CN"), ("80077", "ja"),
]

EXPECTED_TOP_KEYS = {
    "hcid", "title", "subtitle", "cas", "formula", "molecular_weight",
    "structure_image", "overview", "names", "properties", "safety",
    "industry", "suppliers", "data_status", "data_updated_at",
}


def _load(hcid: str, locale: str) -> dict:
    with open(FIXTURES / f"data_api_chemical_{hcid}_{locale}.json") as handle:
        return json.load(handle)


class ProjectionParityTests(unittest.TestCase):
    def test_top_level_partitions_match_page(self):
        for hcid, locale in SAMPLES:
            with self.subTest(hcid=hcid, locale=locale):
                projection = project_chemical(_load(hcid, locale), locale, site_origin=SITE)
                self.assertEqual(set(projection.keys()), EXPECTED_TOP_KEYS)

    def test_title_follows_page_rule(self):
        # 996 zh: 中文名优先于英文名。快照来自当前线上(当地名字段为空),
        # 非中文语言回落英文名 —— 同页面取名链一致。
        zh = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        source_zh = _load("996", "zh-CN")
        self.assertEqual(zh["title"], source_zh.get("name_cn") or source_zh.get("name_local"))
        self.assertEqual(zh["subtitle"], source_zh.get("preferred_name"))
        for locale in ("ja", "en"):
            row = _load("996", "ja")
            title, _ = resolve_title(row, locale)
            self.assertEqual(
                project_chemical(row, locale, site_origin=SITE)["title"], title)

    def test_properties_fields_unique_with_units(self):
        zh = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        labels = [row["label"].strip().lower() for row in zh["properties"]]
        self.assertEqual(len(labels), len(set(labels)), "性质分区内字段不得重复")
        # 熔点值必须带单位(原始文本自带 "°C")
        melting = next((row for row in zh["properties"]
                        if row["label"] == "Melting point"), None)
        self.assertIsNotNone(melting, "样本应含熔点字段")
        self.assertIn("°C", melting["values"][0])

    def test_safety_partitions_exact(self):
        for hcid, locale in SAMPLES:
            with self.subTest(hcid=hcid, locale=locale):
                projection = project_chemical(_load(hcid, locale), locale, site_origin=SITE)
                self.assertEqual(
                    set(projection["safety"].keys()),
                    {"ghs", "hazards", "safety_measures", "toxicity", "regulatory"})

    def test_machine_keys_not_leaked_as_labels(self):
        # wgk/tsca 这类代码键必须映射为语言化字段名(zh 字典里不再是裸键)
        zh = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        all_labels = [row["label"] for rows in zh["safety"].values() for row in rows]
        for bare in ("wgk", "tsca", "rtecs", "hs_code", "ridadr"):
            self.assertNotIn(bare, all_labels, f"裸键 {bare} 不应直接作为字段名")
        regulatory_labels = [row["label"] for row in zh["safety"]["regulatory"]]
        self.assertTrue(any("TSCA" in label for label in regulatory_labels))
        self.assertTrue(any("WGK" in label for label in regulatory_labels))

    def test_evidence_values_rendered_not_placeholder(self):
        zh = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        values = [v for row in zh["properties"] for v in row["values"]]
        self.assertTrue(values)
        # 证据值数组逐项渲染, 不出现占位符
        self.assertFalse(any(v == "—" for v in values))

    def test_structure_image_url(self):
        projection = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        self.assertEqual(
            projection["structure_image"],
            f"{SITE}/img/chemical/996.png")

    def test_synonyms_capped_with_total(self):
        projection = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        self.assertLessEqual(len(projection["names"]["synonyms"]), 20)
        self.assertGreaterEqual(projection["names"]["synonyms_total"],
                                len(projection["names"]["synonyms"]))

    def test_data_status_and_updated_at(self):
        projection = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        self.assertIn(projection["data_status"], ("complete", "updating"))
        self.assertIsNotNone(projection["data_updated_at"])

    def test_locale_uses_local_names(self):
        zh = project_chemical(_load("996", "zh-CN"), "zh-CN", site_origin=SITE)
        ja = project_chemical(_load("996", "ja"), "ja", site_origin=SITE)
        self.assertNotEqual(zh["names"]["local_name"], ja["names"]["local_name"])


class ReactionProjectionTests(unittest.TestCase):
    def _reaction(self):
        return {
            "id": 7, "reaction_smiles": "CCO.CC(=O)O>>CC(=O)OCC",
            "visibility": "public", "moderation_status": "visible",
            "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-02T00:00:00Z",
            "procedure_details": "回流 2 小时后冷却", "safety_notes": None,
            "conditions_detail": "无水条件",
            "temperature": {"value": 78.0, "unit": "CELSIUS"},
            "duration": {"value": 2, "unit": "HOUR"},
            "pressure": None, "atmosphere": "氮气", "ph": None, "reflux": True,
            "source_type": "doi", "doi": "10.1000/x", "patent": None,
            "publication_url": None, "source_citation": None, "note": None,
            "participants": [
                {"id": 1, "role": "REACTANT", "preferred_name": "Ethanol",
                 "iupac_name": None, "molecular_formula": None,
                 "cas_numbers": ["64-17-5"], "name_local": None, "name_cn": "乙醇",
                 "occurrence_count": 1, "amount_value": 10.0, "amount_unit": "mL",
                 "equivalents": 1.0, "yield_percent": None},
                {"id": 2, "role": "PRODUCT", "preferred_name": "Ethyl acetate",
                 "iupac_name": None, "molecular_formula": None,
                 "cas_numbers": ["141-78-6"], "name_local": None, "name_cn": "乙酸乙酯",
                 "occurrence_count": 1, "amount_value": None, "amount_unit": None,
                 "equivalents": None, "yield_percent": 85.0},
            ],
        }

    def test_projection_shape(self):
        projection = project_reaction(self._reaction(), "zh-CN", site_origin=SITE)
        self.assertNotIn("visibility", projection)
        self.assertEqual(projection["hrid"], 7)
        self.assertEqual(projection["title"], "乙醇 → 乙酸乙酯")
        self.assertTrue(projection["equation_image"].endswith("/img/reaction/7.svg"))
        self.assertEqual(projection["participants"][0]["amount"]["unit"], "mL")
        self.assertEqual(projection["participants"][1]["yield_percent"], 85.0)
        self.assertEqual(projection["conditions"]["temperature"]["unit"], "CELSIUS")
        self.assertEqual(projection["references"]["doi"], "10.1000/x")
        self.assertEqual(projection["procedure"], "回流 2 小时后冷却")

    def test_title_rule_prefers_local_name(self):
        projection = project_reaction(self._reaction(), "zh-CN", site_origin=SITE)
        self.assertIn("乙醇", projection["title"])

    def test_title_without_reactant(self):
        reaction = self._reaction()
        reaction["participants"] = [p for p in reaction["participants"] if p["role"] != "REACTANT"]
        projection = project_reaction(reaction, "en", site_origin=SITE)
        self.assertTrue(projection["title"].startswith("→"))


class TitleRuleUnitTests(unittest.TestCase):
    def test_fallback_chain(self):
        base = {"id": 9, "name_local": None, "name_cn": None}
        self.assertEqual(resolve_title({**base, "preferred_name": "Phenol"}, "en")[0], "Phenol")
        self.assertEqual(resolve_title({**base, "iupac_name": "phenol"}, "en")[0], "phenol")
        self.assertEqual(resolve_title({**base, "molecular_formula": "C6H6O"}, "en")[0], "C6H6O")
        self.assertEqual(resolve_title({**base, "cas_numbers": ["108-95-2"]}, "en")[0], "108-95-2")
        self.assertEqual(resolve_title(base, "en")[0], "HCID 9")

    def test_zh_uses_name_cn(self):
        title, secondary = resolve_title(
            {"id": 1, "name_local": None, "name_cn": "苯酚", "preferred_name": "Phenol"},
            "zh-CN")
        self.assertEqual(title, "苯酚")
        self.assertEqual(secondary, "Phenol")

    def test_zh_without_english_uses_iupac_subtitle(self):
        title, secondary = resolve_title(
            {"id": 2, "name_local": None, "name_cn": "苯酚", "preferred_name": None,
             "iupac_name": "phenol"},
            "zh-CN")
        self.assertEqual(title, "苯酚")
        self.assertEqual(secondary, "phenol")


if __name__ == "__main__":
    unittest.main()
