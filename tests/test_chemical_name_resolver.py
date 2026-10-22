"""化合物显示名称 · 唯一解析规则（resolver 规则本身的行为测试在
web/lib/chemicalName.test.mjs）。

本文件锁两件事:

1. API 只补 locale 名称原始字段(name_cn), 由 name_index 批量挂载, 不下发全量;
2. 单链不变量: 任何展示名称的地方都必须消费同一 resolver, 禁止第二套 fallback。
"""

from __future__ import annotations

import os
import re
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
CONSUMERS = [
    "web/components/EntityCard.tsx",
    "web/app/(site)/chemical/[id]/page.tsx",
    "web/app/(site)/reaction/[id]/page.tsx",
    "web/components/workbench/panels/SearchPanel.tsx",
    "web/components/workbench/panels/SavedPanel.tsx",
]

try:
    from tests.db_gate import test_db_or_skip  # noqa: E402

    _RAW_DB_URL = test_db_or_skip()
    DB_URL = "postgresql+asyncpg://" + _RAW_DB_URL.split("://", 1)[1].split("?", 1)[0]
except Exception:  # pragma: no cover - 无 test DB 时跳过 DB 用例
    DB_URL = None

from api.services import chemicals as chemicals_service  # noqa: E402


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# 2. API: name_cn 批量挂载(只补原始字段, 不下发 name_index 全量)
# ---------------------------------------------------------------------------
class _CountingSession:
    """统计 execute 次数, 证明整页一次查询。"""

    def __init__(self, session):
        self._session = session
        self.calls = 0

    async def execute(self, *args, **kwargs):
        self.calls += 1
        return await self._session.execute(*args, **kwargs)


def _run_db(scenario):
    """每个用例独立 engine + 独立事件循环, 用完即 dispose。

    asyncpg 连接绑定创建它的事件循环: 跨 asyncio.run 复用池会报
    "another operation is in progress"(与结构检索测试同因)。
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def runner():
        engine = create_async_engine(DB_URL)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await scenario(session)
        finally:
            await engine.dispose()

    return asyncio.run(runner())


@unittest.skipUnless(DB_URL, "无 test DB: 跳过 name_cn 挂载用例")
class LocalizedNameAttachTests(unittest.TestCase):
    async def _fixture(self, session, *, name: str, name_cn: str | None = None,
                       extra_names: list[tuple[str, str, str, str]] | None = None) -> int:
        from sqlalchemy import text

        chemical_id = (await session.execute(text("""
            INSERT INTO chemistry.chemicals (preferred_name, molecular_formula)
            VALUES (:name, 'C2H6O') RETURNING id
        """), {"name": name})).scalar_one()
        rows = list(extra_names or [])
        if name_cn:
            rows.insert(0, ("name_cn", "cn", "cb", name_cn))
        for kind, lang, source, value in rows:
            await session.execute(text("""
                INSERT INTO chemistry.name_index (chemical_id, name, lang, normalized, source, kind)
                VALUES (:cid, :name, :lang, lower(:name), :source, :kind)
            """), {"cid": chemical_id, "name": value, "lang": lang, "source": source, "kind": kind})
        return chemical_id

    async def _cleanup(self, session, chemical_id: int) -> None:
        from sqlalchemy import text

        await session.execute(text("DELETE FROM chemistry.name_index WHERE chemical_id=:id"), {"id": chemical_id})
        await session.execute(text("DELETE FROM chemistry.chemicals WHERE id=:id"), {"id": chemical_id})
        await session.commit()

    def test_name_cn_attached_for_whole_page_in_one_query(self):
        async def scenario(session):
            with_cn = await self._fixture(session, name="Attach Fixture CN", name_cn="挂载夹具乙醇")
            without_cn = await self._fixture(session, name="Attach Fixture EN")
            await session.commit()
            items = [{"id": with_cn}, {"id": without_cn}, {"id": 2 ** 31 - 1}]
            counting = _CountingSession(session)
            filled = await chemicals_service.attach_localized_names(counting, items)
            result = (counting.calls, [row["name_cn"] for row in filled])
            await self._cleanup(session, with_cn)
            await self._cleanup(session, without_cn)
            return result

        calls, attached = _run_db(scenario)
        self.assertEqual(1, calls, "整页必须一次查询")
        self.assertEqual("挂载夹具乙醇", attached[0])
        self.assertIsNone(attached[1])
        self.assertIsNone(attached[2], "不存在的 id 必须是 None, 不能借位")

    def test_alias_and_supplier_kinds_are_not_display_names(self):
        async def scenario(session):
            cid = await self._fixture(session, name="Alias Fixture", extra_names=[
                ("alias_cn", "cn", "cb", "别名乙醇"),
                ("alias_en", "en", "cb", "Alias Ethanol"),
                ("synonym_en", "en", "pubchem", "Ethyl alcohol"),
                ("supplier", "cn", "cb", "某供应商货名"),
            ])
            await session.commit()
            filled = await chemicals_service.attach_localized_names(session, [{"id": cid}])
            value = filled[0]["name_cn"]
            await self._cleanup(session, cid)
            return value

        self.assertIsNone(_run_db(scenario), "别名/供应商名不得冒充主标题")

    def test_only_cb_cn_name_cn_row_is_used(self):
        """契约: (kind,lang,source)=('name_cn','cn','cb') 三位一体。

        同名 kind 的其他 source、错 lang 的行都必须被拒; 且非法行按字典序更靠前
        (AAA/BBB < ZZZ), 保证"唯一入选"不是靠排序侥幸。
        """
        async def scenario(session):
            cid = await self._fixture(session, name="Contract Fixture", extra_names=[
                ("name_cn", "cn", "cb", "ZZZ CB 主中文名"),
                ("name_cn", "cn", "pubchem", "AAA 其他 source 同 kind"),
                ("name_cn", "en", "cb", "BBB 错 lang 同 kind"),
            ])
            await session.commit()
            filled = await chemicals_service.attach_localized_names(session, [{"id": cid}])
            value = filled[0]["name_cn"]
            await self._cleanup(session, cid)
            return value

        self.assertEqual("ZZZ CB 主中文名", _run_db(scenario))

    def test_empty_items_skip_query(self):
        async def scenario(session):
            counting = _CountingSession(session)
            out = await chemicals_service.attach_localized_names(counting, [])
            return counting.calls, out

        calls, out = _run_db(scenario)
        self.assertEqual(0, calls)
        self.assertEqual([], out)

    def test_fetch_chemicals_payload_carries_name_cn(self):
        async def scenario(session):
            cid = await self._fixture(session, name="Fetch Fixture", name_cn="取数夹具丙醇")
            await session.commit()
            items = await chemicals_service.fetch_chemicals(
                session,
                f"SELECT {chemicals_service.CHEMICAL_SELECT} FROM chemistry.chemicals c WHERE c.id=:id",
                {"id": cid},
            )
            await self._cleanup(session, cid)
            return items

        items = _run_db(scenario)
        self.assertEqual(1, len(items))
        self.assertIn("name_cn", items[0], "payload 形状必须稳定")
        self.assertEqual("取数夹具丙醇", items[0]["name_cn"])


# ---------------------------------------------------------------------------
# 3. 单链不变量: 禁止第二套名称 fallback
# ---------------------------------------------------------------------------
class SingleResolverInvariantTests(unittest.TestCase):
    def test_no_second_fallback_chain_in_web(self):
        offenders = []
        for base, _dirs, files in os.walk(os.path.join(ROOT, "web")):
            if "node_modules" in base or ".next" in base:
                continue
            for fname in files:
                if not fname.endswith((".ts", ".tsx")):
                    continue
                path = os.path.join(base, fname)
                if path.endswith(os.path.join("lib", "chemicalName.ts")):
                    continue
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                if re.search(r"preferred_name\s*\|\|", source):
                    offenders.append(os.path.relpath(path, ROOT))
        self.assertEqual([], offenders, "必须消费 resolveChemicalName, 不允许再手写名称链")

    def test_consumers_use_the_single_resolver(self):
        for rel in CONSUMERS:
            with self.subTest(consumer=rel):
                self.assertIn("resolveChemicalName", _read(rel))

    def test_detail_metadata_shares_page_title_source(self):
        source = _read("web/app/(site)/chemical/[id]/page.tsx")
        meta = source.split("export default async function")[0]
        self.assertIn("resolveChemicalName", meta, "SEO 必须与 H1 同源")
        self.assertIn("title: pageTitle", meta)
        self.assertIn("title: `${pageTitle}｜${t.brand.name}`", meta)
        self.assertIn("t.chemical.descFor(displayName)", meta)
        self.assertNotIn("preferred_name", meta)

    def test_api_attaches_locale_names_at_single_point(self):
        source = _read("api/services/chemicals.py")
        self.assertIn('LOCALIZED_NAME_KIND = "name_cn"', source)
        self.assertIn('LOCALIZED_NAME_LANG = "cn"', source)
        self.assertIn('LOCALIZED_NAME_SOURCE = "cb"', source)
        self.assertIn("AND kind = :kind AND lang = :lang AND source = :source", source)
        self.assertIn("await attach_localized_names(db, items)", source)
        self.assertIn('"name_cn": None', source)
        reactions = _read("api/services/reactions.py")
        self.assertIn("attach_localized_names(db, compounds)", reactions)


if __name__ == "__main__":
    unittest.main()
