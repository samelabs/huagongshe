"""SEO metadata source contracts: parameterized search noindex, EN-only legal
canonical, MCP guide and login metadata. Sitemap behavior is tested against the
real module in web/lib/sitemap.test.mjs.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class SearchMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "web/app/(site)/search/page.tsx").read_text(encoding="utf-8")

    def test_parameterized_search_is_noindex_follow(self):
        # focus 参数（手机顶栏搜索图标 → /search?focus=1）同样视为
        # 内部参数页：noindex,follow，不产生 canonical/hreflang 集合。
        self.assertIn("const hasQuery = Boolean(params.q || params.mode || params.page || params.focus);", self.src)
        self.assertIn("robots: { index: false, follow: true }", self.src)

    def test_bare_search_entry_has_canonical_and_description(self):
        self.assertIn('localeAlternates("/search", locale)', self.src)
        self.assertIn("description: t.search.seoDesc", self.src)
        self.assertIn("title: t.search.title", self.src)

    def test_no_query_param_canonical_generation(self):
        # 不为查询词生成 canonical/hreflang: 带 hasQuery 的分支只返回 robots
        branch = self.src[self.src.index("if (hasQuery)"):self.src.index("return {", self.src.index("if (hasQuery)"))]
        self.assertNotIn("alternates", branch)

    def test_search_logic_untouched(self):
        # 既有检索/权限/跳转/分页逻辑保留
        for anchor in ("cas_fetch_chemical_id", "data.has_more === true",
                       "PAGE_SIZE = 30", "err.status === 401"):
            self.assertIn(anchor, self.src)

    def test_seo_desc_key_in_all_five_locales(self):
        for loc in ("zh-CN", "en", "ja", "ko", "de"):
            src = (REPO / f"web/lib/i18n/locales/{loc}.ts").read_text(encoding="utf-8")
            self.assertIn("seoDesc:", src.split("search: {")[1].split("\n  },")[0],
                          f"search.seoDesc missing in {loc}")


class LegalPagesTests(unittest.TestCase):
    PAGES = ("terms", "privacy", "support")

    def test_en_is_sole_canonical_non_en_noindex(self):
        for slug in self.PAGES:
            src = (REPO / f"web/app/(site)/{slug}/page.tsx").read_text(encoding="utf-8")
            self.assertIn('const canonical = "/en/%s";' % slug, src)
            self.assertIn('if (locale === "en")', src)
            self.assertIn("robots: { index: false, follow: true }", src)
            # 不添加 hreflang(不存在真实译文)
            self.assertNotIn("localeAlternates", src)

    def test_english_body_preserved(self):
        # 正文未重写: 英文法律原文仍在
        for slug, heading in (("terms", "Terms of Service"),
                              ("privacy", "Privacy Policy"),
                              ("support", "Support")):
            src = (REPO / f"web/app/(site)/{slug}/page.tsx").read_text(encoding="utf-8")
            # 版式件 PageHead 承担 h1：标题以 props 表达（渲染仍是唯一 h1）
            self.assertIn(f'title="{heading}"', src)
            self.assertIn("Effective October 6, 2026", src) if slug == "terms" else None

    def test_no_hreflang_claims_for_translations(self):
        for slug in self.PAGES:
            src = (REPO / f"web/app/(site)/{slug}/page.tsx").read_text(encoding="utf-8")
            self.assertNotIn("hreflang", src)

    def test_english_body_root_marks_lang_en(self):
        # A2-3: 英文正文根内容容器显式 lang="en"(不动全站 <html lang>)
        for slug in self.PAGES:
            src = (REPO / f"web/app/(site)/{slug}/page.tsx").read_text(encoding="utf-8")
            self.assertIn('<article lang="en" className="guide-page legal-page">',
                          src, f"{slug} root content container missing lang=\"en\"")


class McpGuideMetadataTests(unittest.TestCase):
    def test_mcp_guide_layout_metadata_via_server_layout(self):
        # A2-2: Client Component 页面由同级 server layout 提供 metadata,
        # 不改 page.tsx 的 "use client" 与交互
        layout = (REPO / "web/app/(site)/mcp-guide/layout.tsx").read_text(encoding="utf-8")
        page = (REPO / "web/app/(site)/mcp-guide/page.tsx").read_text(encoding="utf-8")
        self.assertIn("export async function generateMetadata", layout)
        self.assertIn('localeAlternates("/mcp-guide", locale)', layout)
        self.assertIn("description: t.mcp.heroBody", layout)
        # 无 noindex —— 允许索引
        self.assertNotIn("robots", layout)
        # 页面本体保持 Client Component, 交互/连接信息未被触碰
        self.assertIn('"use client"', page)


class LoginMetadataTests(unittest.TestCase):
    def test_login_noindex_follow(self):
        src = (REPO / "web/app/(site)/login/page.tsx").read_text(encoding="utf-8")
        self.assertIn("robots: { index: false, follow: true }", src)

    def test_login_behavior_untouched(self):
        src = (REPO / "web/app/(site)/login/page.tsx").read_text(encoding="utf-8")
        for anchor in ("safeNextPath", "AccountForm", "nextPath"):
            self.assertIn(anchor, src)


if __name__ == "__main__":
    unittest.main()
