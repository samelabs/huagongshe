"""CB locale 读取测试(2026-10 Chemical Detail 后端 locale)。

覆盖任务卡 §6:
- requested locale 存在 → 该 locale; 缺失 → en; 双缺 → none(absent)
- 未指定 locale → en; 非法 locale → en
- 多 CB row 时优先当前 cb_number(imprint)对应行
- locale 切换不改 PB payload(PB invariant)
- en/ja/ko/de prose 进入正确 semantic group, 不全落 notes
- supplier 行为不变(与 locale 无关, 恒同一次读取)

纯单元测试(桩 db), 不依赖 TEST_DATABASE_URL。
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.services import cb as cb_module  # noqa: E402
from api.services import chemical_semantic as cs  # noqa: E402


def _row(locale: str, cb_number: str | None, entry: dict | None = None):
    return {"chemical_id": 1, "cas_number": "50-00-0", "entry": entry,
            "last_status": "ok", "fetched_at": None, "cb_number": cb_number,
            "_locale": locale}  # _locale 仅测试观测用


class _Db:
    """按 (locale, match_cb) 返回预置行的桩 db。

    get_externals_row 的四步查询顺序为 (requested,True)→(en,True)→
    (requested,False)→(en,False); 桩记录每次查询的 locale 与 SQL 形态,
    供顺序断言。
    """

    def __init__(self, table: dict):
        # table: {(locale, cb_number_or_None): row}; key 中 cb_number=None
        # 表示 legacy 任意行(不带 cb 匹配)
        self.table = table
        self.queries: list[tuple[str, bool]] = []

    def _find(self, locale: str, match_cb: bool):
        # match_cb 查询: 化学品主表 imprint 假定 cb_number="CB1"
        imprint = "CB1"
        if match_cb:
            return self.table.get((locale, imprint))
        for (loc, cbn), row in self.table.items():
            if loc == locale and cbn != imprint:
                return row
        return None

    async def execute(self, sql, params=None):
        locale = (params or {}).get("locale", "zh-CN")
        match_cb = "JOIN chemistry.chemicals" in str(sql)
        self.queries.append((locale, match_cb))
        row = self._find(locale, match_cb)

        class _Mappings:
            def __init__(self, r):
                self.r = r

            def fetchone(self):
                return self.r

        class _Result:
            def __init__(self, r):
                self._m = _Mappings(r)

            def mappings(self):
                return self._m

        return _Result(row)


class NormalizeLocaleTests(unittest.TestCase):
    def test_valid_locales_pass_through(self):
        for loc in ("zh-CN", "en", "ja", "ko", "de"):
            self.assertEqual(cb_module.normalize_cb_locale(loc), loc)

    def test_missing_invalid_fallback_en(self):
        for loc in (None, "", "fr", "zh-TW", "EN", "ja-JP", "xx"):
            self.assertEqual(cb_module.normalize_cb_locale(loc), "en")


class RowSelectionTests(unittest.TestCase):
    def _get(self, table, locale="ja"):
        db = _Db(table)
        row = asyncio.run(cb_module.get_externals_row(db, 1, locale=locale))
        return db, row

    def test_ja_present_returns_ja(self):
        db, row = self._get({("ja", "CB1"): _row("ja", "CB1", {"identity": {"cn": "ja行"}})}, locale="ja")
        self.assertIsNotNone(row)
        self.assertEqual(row["entry"]["identity"]["cn"], "ja行")
        self.assertEqual(db.queries[0], ("ja", True))  # 首查即 requested+imprint

    def test_ko_present_returns_ko(self):
        db, row = self._get({("ko", "CB1"): _row("ko", "CB1", {"identity": {"cn": "ko行"}})}, locale="ko")
        self.assertIsNotNone(row)
        self.assertEqual(row["entry"]["identity"]["cn"], "ko行")

    def test_de_present_returns_de(self):
        _, row = self._get({("de", "CB1"): _row("de", "CB1", {"identity": {"cn": "de行"}})}, locale="de")
        self.assertIsNotNone(row)
        self.assertEqual(row["entry"]["identity"]["cn"], "de行")

    def test_zh_present_returns_zh(self):
        _, row = self._get({("zh-CN", "CB1"): _row("zh-CN", "CB1", {"identity": {"cn": "zh行"}})}, locale="zh-CN")
        self.assertIsNotNone(row)
        self.assertEqual(row["entry"]["identity"]["cn"], "zh行")

    def test_requested_missing_falls_back_en_imprint(self):
        db, row = self._get({("en", "CB1"): _row("en", "CB1", {"identity": {"cn": "en行"}})})
        self.assertIsNotNone(row)
        self.assertEqual(row["entry"]["identity"]["cn"], "en行")
        # 顺序: (ja,True) 空 → (en,True) 命中
        self.assertEqual(db.queries, [("ja", True), ("en", True)])

    def test_requested_missing_falls_back_en_legacy(self):
        db, row = self._get({("en", "CB9"): _row("en", "CB9", {"identity": {"cn": "en-legacy"}})})
        self.assertIsNotNone(row)
        self.assertEqual(row["entry"]["identity"]["cn"], "en-legacy")
        self.assertEqual(db.queries, [
            ("ja", True), ("en", True), ("ja", False), ("en", False)])

    def test_requested_and_en_both_missing_returns_none(self):
        db, row = self._get({("zh-CN", "CB1"): _row("zh-CN", "CB1")})
        self.assertIsNone(row)
        # 四步全走完(未越界查询其他 locale)
        self.assertEqual(db.queries, [
            ("ja", True), ("en", True), ("ja", False), ("en", False)])

    def test_unspecified_locale_defaults_en(self):
        db = _Db({("en", "CB1"): _row("en", "CB1", {"identity": {"cn": "en行"}})})
        row = asyncio.run(cb_module.get_externals_row(db, 1))
        self.assertIsNotNone(row)
        self.assertEqual(db.queries[0], ("en", True))

    def test_invalid_locale_defaults_en(self):
        db = _Db({("en", "CB1"): _row("en", "CB1", {"identity": {"cn": "en行"}})})
        row = asyncio.run(cb_module.get_externals_row(db, 1, locale="fr"))
        self.assertIsNotNone(row)
        self.assertEqual(db.queries[0], ("en", True))

    def test_imprint_row_preferred_over_legacy(self):
        # 同 locale 下: imprint 行优先于 legacy 行(第 1 步命中, 不走第 3 步)
        db = _Db({
            ("ja", "CB9"): _row("ja", "CB9", {"identity": {"cn": "ja-legacy"}}),
            ("ja", "CB1"): _row("ja", "CB1", {"identity": {"cn": "ja-imprint"}}),
        })
        row = asyncio.run(cb_module.get_externals_row(db, 1, locale="ja"))
        self.assertEqual(row["entry"]["identity"]["cn"], "ja-imprint")
        self.assertEqual(db.queries, [("ja", True)])

    def test_locale_equal_en_queries_deduped(self):
        # locale=en: (en,True) 命中即返回 — 全程 1 次查询, 绝无重复组合
        db = _Db({("en", "CB1"): _row("en", "CB1")})
        asyncio.run(cb_module.get_externals_row(db, 1, locale="en"))
        self.assertEqual(db.queries, [("en", True)])
        # 双缺场景(en 不存在): (en,True)/(en,False) 各只查一次 — 共 2 次而非 4 次
        db2 = _Db({})
        asyncio.run(cb_module.get_externals_row(db2, 1, locale="en"))
        self.assertEqual(db2.queries, [("en", True), ("en", False)])


class SingleSourceTests(unittest.TestCase):
    """规则源唯一性: chemical_semantic 不得再私维护标题表, 分组走 caslib。"""

    def test_semantic_module_has_no_private_title_table(self):
        import inspect
        src = inspect.getsource(cs)
        self.assertIn("from caslib.parse_cpp import", src)
        self.assertNotIn("_CB_PROSE_GROUPS", src)
        # 不再出现按语言的重复标题罗列(抽查几个标题只允许经 caslib 常量)
        for title in ("使用用途", "Vorbereitung Met", "순도시험", "説明"):
            self.assertNotIn(f'"{title}"', src)

    def test_parser_collected_titles_all_classified(self):
        """_PROSE_TITLES 白名单内每个标题都有明确分组(不为 notes 意外漏配)。"""
        from caslib import parse_cpp
        expected_notes = {"定義", "정의", "Definition",
                          "순도시험", "확인시험", "정량법"}
        for title in parse_cpp._PROSE_TITLES:
            group = parse_cpp.classify_prose_title(title)
            if title not in expected_notes:
                self.assertNotEqual(group, "notes", f"{title!r} 应有分组")
                self.assertIn(group, {"uses", "preparation", "properties",
                                      "toxicity", "packaging"})
        # notes 组标题仍判 notes
        for title in expected_notes:
            self.assertEqual(parse_cpp.classify_prose_title(title), "notes")

    def test_semantic_group_matches_caslib_classifier(self):
        from caslib import parse_cpp
        for title in ("用途", "説明", "용도", "Uses", "Verwenden",
                      "調製方法", "화학적 성질", "Chemische Eigensc"):
            self.assertEqual(cs._cb_prose_group(title),
                             parse_cpp.classify_prose_title(title), title)


class ProseClassificationTests(unittest.TestCase):
    def _groups(self, titles):
        entry = {"prose": [{"title": t, "text": "x"} for t in titles]}
        return {g: [i["title"] for i in v]
                for g, v in cs._prose_split(entry).items() if v}

    def test_zh_titles_unchanged(self):
        g = self._groups(["用途", "生产方法", "化学性质", "毒性", "储运特性", "备注外标题"])
        self.assertEqual(g.get("uses"), ["用途"])
        self.assertEqual(g.get("preparation"), ["生产方法"])
        self.assertEqual(g.get("properties"), ["化学性质"])
        self.assertEqual(g.get("toxicity"), ["毒性"])
        self.assertEqual(g.get("packaging"), ["储运特性"])
        self.assertEqual(g.get("notes"), ["备注外标题"])

    def test_ja_titles_grouped(self):
        g = self._groups(["使用用途", "説明", "一般的な説明", "調製方法", "製造方法",
                          "化学的特性", "定義", "未知の見出し"])
        self.assertEqual(g.get("uses"), ["使用用途", "説明", "一般的な説明"])
        self.assertEqual(g.get("preparation"), ["調製方法", "製造方法"])
        self.assertEqual(g.get("properties"), ["化学的特性"])
        self.assertEqual(g.get("notes"), ["定義", "未知の見出し"])

    def test_ko_titles_grouped(self):
        g = self._groups(["용도", "개요", "일반 설명", "생산 방법", "제조 방법",
                          "화학적 성질", "순도시험"])
        self.assertEqual(g.get("uses"), ["용도", "개요", "일반 설명"])
        self.assertEqual(g.get("preparation"), ["생산 방법", "제조 방법"])
        self.assertEqual(g.get("properties"), ["화학적 성질"])
        self.assertEqual(g.get("notes"), ["순도시험"])

    def test_en_titles_grouped(self):
        g = self._groups(["Uses", "Description", "General Description", "Occurrence",
                          "History", "Preparation", "Production Method",
                          "Definition"])
        self.assertEqual(g.get("uses"), ["Uses", "Description", "General Description",
                                          "Occurrence", "History"])
        self.assertEqual(g.get("preparation"), ["Preparation", "Production Method"])
        self.assertEqual(g.get("notes"), ["Definition"])
        # "Chemical Properties" 不在 parser 采集白名单(_PROSE_TITLES),
        # 分类器对未知标题判 notes — 与 parser 集合一致, 不虚构可达标题
        self.assertEqual(cs._cb_prose_group("Chemical Properties"), "notes")

    def test_de_titles_grouped(self):
        g = self._groups(["Verwenden", "Beschreibung", "Allgemeine Besch",
                          "Vorbereitung Met", "synthetische",
                          "Chemische Eigensc"])
        self.assertEqual(g.get("uses"), ["Verwenden", "Beschreibung",
                                          "Allgemeine Besch"])
        self.assertEqual(g.get("preparation"), ["Vorbereitung Met", "synthetische"])
        self.assertEqual(g.get("properties"), ["Chemische Eigensc"])


class SemanticShapeTests(unittest.TestCase):
    def test_first_level_structure_unchanged(self):
        out = cs.build_semantic_detail(
            pb={"record_description": "d"},
            cb_entry={"identity": {"cn": "x"}, "prose": []},
            cb_suppliers=[],
            pb_state={"state": "current", "fetched_at": None},
            cb_state={"state": "current", "fetched_at": None},
        )
        self.assertEqual(
            list(out.keys()),
            ["description", "names", "properties", "safety",
             "industry", "suppliers", "provenance"])

    def test_pb_block_identical_across_locales(self):
        """PB invariant: cb_entry 换语言行, PB 侧投影逐字节一致。"""
        pb = {"record_description": "water", "xlogp": -0.5,
              "physical_properties": {"mp": "0"}}
        outs = []
        for cb_entry in (
            {"identity": {"cn": "zh"}, "prose": []},
            {"identity": {"cn": "ja"}, "prose": [{"title": "説明", "text": "y"}]},
            {"identity": {"cn": "de"}, "prose": [{"title": "Verwenden", "text": "z"}]},
        ):
            out = cs.build_semantic_detail(
                pb=pb, cb_entry=cb_entry, cb_suppliers=[],
                pb_state={"state": "current", "fetched_at": None},
                cb_state={"state": "current", "fetched_at": None})
            outs.append({k: out[k] for k in ("description", "properties")})
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0], outs[2])


if __name__ == "__main__":
    unittest.main()
