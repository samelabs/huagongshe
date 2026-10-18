"""MCP 对外输出映射: 不暴露内部字段, 业务数据不丢。"""
import json
import unittest

from api.mcp_server import (
    _public_chemical, _public_reaction, _public_search, _public_skill,
)

INTERNAL = ('"source"', "provenance", "pb_", "cb_", "job_id", "enrichment",
            "moderation_status", "ord_record_id", "is_following", "follower_count",
            "avatar_url", "match_basis", "cas_fetch", "references", "kdense",
            '"origin"', "owner_id", "cbsid", "cb-supplier")


def _assert_clean(tc, data):
    dumped = json.dumps(data, ensure_ascii=False)
    for word in INTERNAL:
        tc.assertNotIn(word, dumped, f"MCP 输出含内部字段: {word}")


SEMANTIC = {
    "description": {"source": "pubchem", "record_description": "desc"},
    "names": {"cb_identity": {"cn": "水", "en": "water", "formula": "H2O", "mw": 18.0},
              "cb_aliases": [{"value": "aqua", "source": "cb"}]},
    "properties": {
        "pb_computed": {"xlogp": -0.5},
        "pb_physical_properties": {"entries": {
            "Boiling Point": [{"value": "100", "unit": "°C", "references": ["1"]}]}},
        "cb_experimental": [{"label": "熔点", "text": "0 °C", "v": 0, "unit": "°C", "source": "cb"}],
        "cb_prose": [{"title": "化学性质", "text": "无色液体", "source": "cb"}],
    },
    "safety": {
        "pb_sections": {"ghs_classification": {"entries": {"Signal": [{"value": "Warning"}]}}},
        "cb_safety": {"wgk": "1"},
        "cb_toxicity": [{"title": "毒性", "text": "低", "source": "cb"}],
        "cb_packaging": [{"title": "储存", "text": "常温", "source": "cb"}],
    },
    "industry": {
        "pb_sections": {"uses_and_manufacturing": {"entries": {"Uses": ["solvent"]}}},
        "cb_uses": [{"title": "用途", "text": "溶剂", "source": "cb"}],
        "cb_preparation": [{"title": "制备", "text": "蒸馏", "source": "cb"}],
        "cb_updown": {"up": [{"name": "氢气"}], "down": [{"name": "冰"}]},
        "cb_price": [{"updated": "2026-01-01", "code": "W1", "name": "水", "package": "1L", "price": "10"}],
        "cb_notes": [{"title": "注意", "text": "无", "source": "cb"}],
    },
    "suppliers": {"items": [{"ref": "r1", "name": "SupA", "phone": "1", "email": "a@b.c",
                             "website": None, "purity": "99%", "pack_price": "1L/10", "remark": None}]},
    "provenance": {"pubchem": {"state": "current", "fetched_at": "x", "job_id": 1},
                   "cb": {"state": "current", "applicable": True}},
}


class PublicChemicalTests(unittest.TestCase):
    def test_full_clean_and_complete(self):
        raw = {"id": 1, "pubchem_cid": 962, "cas_numbers": ["7732-18-5"], "similarity": None,
               "follower_count": 3, "is_following": False, "synonyms": ["water"],
               "details": SEMANTIC,
               "enrichment": {"status": "current", "sources": {"pubchem": "current", "cb": "current"}, "job_id": None}}
        out = _public_chemical(raw)
        _assert_clean(self, out)
        self.assertEqual(out["pubchem_cid"], 962)
        self.assertEqual(out["cas_numbers"], ["7732-18-5"])
        d = out["details"]
        self.assertEqual(d["description"], "desc")
        self.assertEqual(d["names"]["chinese_name"], "水")
        self.assertEqual(d["names"]["aliases"], ["aqua"])
        self.assertEqual(d["computed_properties"], {"xlogp": -0.5})
        self.assertEqual(d["experimental_properties"], {"Boiling Point": ["100 °C"]})
        self.assertEqual(d["physical_data"][0]["value"], "0 °C")
        self.assertEqual(d["chemical_properties"][0]["text"], "无色液体")
        self.assertEqual(d["safety"]["ghs_classification"], {"Signal": ["Warning"]})
        self.assertEqual(d["safety"]["safety_data"], {"Water hazard class (WGK)": "1"})
        self.assertEqual(d["applications"]["uses_and_manufacturing"], {"Uses": ["solvent"]})
        self.assertEqual(d["related_products"]["upstream_materials"], ["氢气"])
        self.assertEqual(d["reagent_prices"][0]["price"], "10")
        self.assertEqual(d["suppliers"][0]["package_price"], "1L/10")

    def test_core_clean(self):
        out = _public_chemical({"id": 1, "details": None, "enrichment": {"status": "current"}})
        _assert_clean(self, out)
        self.assertIsNone(out["details"])

    def test_unknown_service_key_not_exposed(self):
        # 服务层将来新增的键(此处以未知内部状态键模拟)不得自动进入 MCP 输出
        raw = {"id": 1, "details": None, "internal_audit_state": "queued"}
        out = _public_chemical(raw)
        self.assertNotIn("internal_audit_state", out)
        self.assertEqual(out, {"id": 1, "details": None})

    def test_supplier_ref_with_raw_cbsid_is_not_exposed(self):
        # 即使上游语义详情还带着原站标识形态的 ref(cb-supplier:{cbsid}),
        # MCP 出口也不得出现供应商编号。
        semantic = json.loads(json.dumps(SEMANTIC))
        semantic["suppliers"]["items"][0]["ref"] = "cb-supplier:1436986"
        out = _public_chemical({"id": 1, "details": semantic})
        _assert_clean(self, out)
        dumped = json.dumps(out, ensure_ascii=False)
        self.assertNotIn("1436986", dumped)


class PublicReactionTests(unittest.TestCase):
    def test_reaction_clean(self):
        raw = {"id": 5, "visibility": "public", "moderation_status": "visible", "ord_record_id": 9,
               "ord_id": "ord-1", "dataset_name": "uspto", "source_citation": "uspto",
               "is_owner": False, "is_following": False, "follower_count": 2,
               "creator": {"username": "u", "display_name": "U", "avatar_url": "/a.png", "active": True, "is_following": True},
               "participants": [{"id": 1, "role": "REACTANT", "similarity": None}]}
        out = _public_reaction(raw)
        _assert_clean(self, out)
        # 契约冻结：HTTP 详情新增的 creator.is_following 不得进入 MCP 输出
        self.assertNotIn("is_following", out["creator"])
        self.assertNotIn("avatar_url", out["creator"])
        self.assertEqual(out["ord_id"], "ord-1")
        self.assertEqual(out["source_citation"], "uspto")
        self.assertEqual(out["participants"], [{"id": 1, "role": "REACTANT"}])


    def test_unknown_service_key_not_exposed(self):
        raw = {"id": 5, "visibility": "public", "moderation_state_v2": "ok",
               "participants": []}
        out = _public_reaction(raw)
        self.assertNotIn("moderation_state_v2", out)
        self.assertEqual(out["visibility"], "public")


class FieldLabelForeignSynonymTests(unittest.TestCase):
    """规范表外语写法：CB 原站多语言安全键落到统一规范名；法规专名保持原样。"""

    def test_foreign_synonyms_resolve_to_canonical(self):
        from api.services.field_labels import field_label
        self.assertEqual(field_label("Gefahrenhinweise"), "GHS hazard statements")
        self.assertEqual(field_label("危険有害性情報"), "GHS hazard statements")
        self.assertEqual(field_label("유해·위험 문구"), "GHS hazard statements")
        self.assertEqual(field_label("Alarmwort"), "GHS signal word")
        self.assertEqual(field_label("신호 어"), "GHS signal word")
        self.assertEqual(field_label("防范说明"), "GHS precautionary statements")
        self.assertEqual(field_label("危险性符号(GHS)"), "Hazard symbols")
        self.assertEqual(field_label("Speicherklasse"), "Storage class")
        self.assertEqual(field_label("hazard_note"), "Hazard note")
        self.assertEqual(field_label("위험 참고 사항"), "Hazard note")
        self.assertEqual(field_label("Toxizität"), "Toxicity")
        self.assertEqual(field_label("독성"), "Toxicity")
        self.assertEqual(field_label("REACH 注册登记"), "REACH registrations")

    def test_regulation_names_pass_through(self):
        from api.services.field_labels import field_label
        self.assertEqual(field_label("消防法"), "消防法")
        self.assertEqual(field_label("DOT Classification"), "DOT Classification")
        self.assertEqual(field_label("유해화학물질 필터링"), "유해화학물질 필터링")


class PublicSearchTests(unittest.TestCase):
    def test_search_clean(self):
        raw = {"query": "x", "chemicals": [{"id": 1, "similarity": None}, {"id": 2, "similarity": 0.8}],
               "reactions": [{"id": 3, "dataset_name": "user_submitted", "match_basis": "doi"}],
               "cas_fetch_pending": True}
        out = _public_search(raw)
        _assert_clean(self, out)
        self.assertTrue(out["lookup_pending"])
        self.assertEqual(out["chemicals"], [{"id": 1}, {"id": 2, "similarity": 0.8}])
        self.assertEqual(out["reactions"], [{"id": 3, "dataset_name": "User submitted"}])


class PublicSkillTests(unittest.TestCase):
    def test_skill_clean(self):
        out = _public_skill({"id": 1, "slug": "s", "origin": "kdense", "owner_id": 7, "title": "T"})
        _assert_clean(self, out)
        self.assertEqual(out, {"id": 1, "slug": "s", "title": "T"})


if __name__ == "__main__":
    unittest.main()
