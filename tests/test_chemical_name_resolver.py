"""化合物显示名称 · 唯一解析规则 (0912 locale-chemical-name)。

背景(审计结论, 全部来自真实 schema 与数据):

- `chemistry.chemicals.preferred_name` ← PubChem `Title`(或 record_title)/ CB `identity.en`
  —— English 常用名; `iupac_name` ← PubChem `IUPACName` —— 系统名。
- `chemistry.name_index` 是派生镜像, `lang` 只有 cn/en, `kind` 五种:
  name_cn(172,801 行 / 172,801 chemical_id, 即每化合物至多一条, 来自 CB identity.cn)、
  alias_cn、alias_en、synonym_en、supplier(供应商名, 非展示名)。
- 中文名此前只有 detail 页的 CB evidence 区块可见; H1/搜索结果/SEO 各自一套 fallback,
  且 SEO <title> 是裸 `HCID {id}`, 与 OG title 不一致。

本文件锁三件事:

1. resolver 规则本身(直接执行 web/lib/chemicalName.ts 真身, 不是复制逻辑);
2. API 只补 locale 名称原始字段(name_cn), 由 name_index 批量挂载, 不下发全量;
3. 单链不变量: 任何展示名称的地方都必须消费同一 resolver, 禁止第二套 fallback。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest

os.environ.setdefault("HGS_DATABASE_URL", os.environ.get("TEST_DATABASE_URL", ""))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
RESOLVER_TS = os.path.join(WEB, "lib", "chemicalName.ts")
CONSUMERS = [
    "web/components/ChemicalResult.tsx",
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
# 1. resolver 规则(执行真身 TS 模块)
# ---------------------------------------------------------------------------
NODE_CASES = """
const m = await import(RESOLVER_URL);
const label = (id) => `HCID ${id}`;
const cases = {
  zh_cn_and_en: [{ id: 1, name_cn: "乙醇", preferred_name: "Ethanol", iupac_name: "ethanol", molecular_formula: "C2H6O" }, "zh-CN"],
  zh_en_only: [{ id: 2, preferred_name: "Ethanol" }, "zh-CN"],
  zh_systematic_only: [{ id: 3, iupac_name: "oxalonitrile", molecular_formula: "C2N2" }, "zh-CN"],
  zh_formula_only: [{ id: 4, molecular_formula: "C2N2" }, "zh-CN"],
  zh_nothing: [{ id: 5 }, "zh-CN"],
  ja_cn_and_en: [{ id: 6, name_cn: "乙醇", preferred_name: "Ethanol" }, "ja-JP"],
  en_locale_with_cn: [{ id: 7, name_cn: "乙醇", preferred_name: "Ethanol" }, "en-US"],
  zh_blank_cn: [{ id: 8, name_cn: "   ", preferred_name: "Cyanogen" }, "zh-CN"],
  zh_cn_equals_en: [{ id: 9, name_cn: "Cyanogen", preferred_name: "Cyanogen" }, "zh-CN"],
};
const out = {};
for (const [key, [chem, locale]] of Object.entries(cases)) out[key] = m.resolveChemicalName(chem, label, locale);
out.site_locale = m.SITE_LOCALE;
console.log(JSON.stringify(out));
"""


def _run_resolver() -> dict:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node 不可用: 跳过 resolver 真身执行")
    if not os.path.exists(RESOLVER_TS):
        raise unittest.SkipTest(f"resolver 缺失: {RESOLVER_TS}")
    script = f'const RESOLVER_URL = "file://{RESOLVER_TS}";\n' + NODE_CASES
    proc = subprocess.run(
        [node, "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=WEB, timeout=120,
    )
    if proc.returncode != 0:
        raise AssertionError(f"resolver 执行失败: {proc.stderr[-800:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


class ResolverRuleTests(unittest.TestCase):
    """locale -> 本地化名 -> 英文常用名 -> 系统名 -> 分子式 -> HCID。"""

    @classmethod
    def setUpClass(cls):
        cls.result = _run_resolver()

    def test_zh_with_localized_and_english(self):
        got = self.result["zh_cn_and_en"]
        self.assertEqual(("乙醇", "Ethanol", "name_cn"), (got["title"], got["secondary"], got["source"]))

    def test_zh_english_only_no_secondary_duplication(self):
        got = self.result["zh_en_only"]
        self.assertEqual(("Ethanol", "preferred_name"), (got["title"], got["source"]))
        self.assertIsNone(got["secondary"], "主标题本身就是英文名时不得重复 secondary")

    def test_zh_systematic_then_formula_then_hcid(self):
        self.assertEqual(("oxalonitrile", "iupac_name"), (self.result["zh_systematic_only"]["title"], self.result["zh_systematic_only"]["source"]))
        self.assertEqual(("C2N2", "molecular_formula"), (self.result["zh_formula_only"]["title"], self.result["zh_formula_only"]["source"]))
        self.assertEqual(("HCID 5", "hcid"), (self.result["zh_nothing"]["title"], self.result["zh_nothing"]["source"]))

    def test_other_locale_falls_back_to_english(self):
        for key in ("ja_cn_and_en", "en_locale_with_cn"):
            got = self.result[key]
            self.assertEqual("Ethanol", got["title"], key)
            self.assertEqual("preferred_name", got["source"], key)
            self.assertIsNone(got["secondary"], key)

    def test_blank_and_identical_names_do_not_leak(self):
        blank = self.result["zh_blank_cn"]
        self.assertEqual(("Cyanogen", "preferred_name"), (blank["title"], blank["source"]))
        same = self.result["zh_cn_equals_en"]
        self.assertEqual("Cyanogen", same["title"])
        self.assertIsNone(same["secondary"], "本地化名与英文名同串时不得重复展示")

    def test_site_locale_is_zh_cn(self):
        self.assertEqual("zh-CN", self.result["site_locale"])


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
                       extra_names: list[tuple[str, str, str]] | None = None) -> int:
        from sqlalchemy import text

        chemical_id = (await session.execute(text("""
            INSERT INTO chemistry.chemicals (preferred_name, molecular_formula)
            VALUES (:name, 'C2H6O') RETURNING id
        """), {"name": name})).scalar_one()
        rows = list(extra_names or [])
        if name_cn:
            rows.insert(0, ("name_cn", "cn", name_cn))
        for kind, lang, value in rows:
            await session.execute(text("""
                INSERT INTO chemistry.name_index (chemical_id, name, lang, normalized, source, kind)
                VALUES (:cid, :name, :lang, lower(:name), 'cb', :kind)
            """), {"cid": chemical_id, "name": value, "lang": lang, "kind": kind})
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
                ("alias_cn", "cn", "别名乙醇"),
                ("alias_en", "en", "Alias Ethanol"),
                ("synonym_en", "en", "Ethyl alcohol"),
                ("supplier", "cn", "某供应商货名"),
            ])
            await session.commit()
            filled = await chemicals_service.attach_localized_names(session, [{"id": cid}])
            value = filled[0]["name_cn"]
            await self._cleanup(session, cid)
            return value

        self.assertIsNone(_run_db(scenario), "别名/供应商名不得冒充主标题")

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
        self.assertIn("await attach_localized_names(db, items)", source)
        self.assertIn('"name_cn": None', source)
        reactions = _read("api/services/reactions.py")
        self.assertIn("attach_localized_names(db, compounds)", reactions)


if __name__ == "__main__":
    unittest.main()
