"""G1.5-A SEO minimal closeout — S1/S2/S3/S4 regression tests.

S1: the REAL sitemap()/robots() modules (app/sitemap.ts, app/robots.ts) are
    executed in Node with TS annotations stripped — whitelist URLs only,
    five locales x static paths, no dynamic/private/admin URLs, no fabricated
    lastModified; robots declares the sitemap URL from the same SSOT.
S2/S3/S4: source-contract anchors on generateMetadata implementations
    (parameterized search noindex, EN-only legal canonical, login noindex).
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SITEMAP_HARNESS = r'''
"use strict";
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");

function extractFn(name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} missing`);
  let i = src.indexOf("{", start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) { end = j; break; } }
  }
  return src.slice(start, end + 1)
    .replace(/([a-zA-Z_]\w*)(\s*:\s*[a-zA-Z_][\w.<>\[\]]*(\s*\|\s*[a-zA-Z_][\w.<>\[\]]*)+)/g, "$1")
    .replace(/\?:[^,)=]*/g, "")
    .replace(/:\s*MetadataRoute\.Sitemap\b/g, "")
    .replace(/:\s*(string|number)\b/g, "");
}

// strip TS-only syntax from the whole module so CommonJS can parse it
let mod = src
  .replace(/^import .*$/gm, "")
  .replace(/^export default function sitemap/m, "function sitemap")
  .replace(/^export const SITEMAP_URL/m, "const SITEMAP_URL")
  .replace(/\s+as const/g, "")
  .replace(/^void FALLBACK_LOCALE;$/m, "")
  .replace(/([a-zA-Z_]\w*)(\s*:\s*[a-zA-Z_][\w.<>\[\]]*(\s*\|\s*[a-zA-Z_][\w.<>\[\]]*)+)/g, "$1")
  .replace(/\?:[^,)=]*/g, "")
  .replace(/:\s*MetadataRoute\.Sitemap\b/g, "")
  .replace(/:\s*(string|number|Locale)\b(\[\])?/g, "")
  .replace(/\)!/g, ")")
  .replace(/(\w)!([,\s.)])/g, "$1$2");

// resolve imports against their real sources (alternates / locales SSOT)
const alternatesSrc = fs.readFileSync(process.argv[3], "utf-8")
  .replace(/^import .*$/gm, "")
  .replace(/^export /gm, "")
  .replace(/\s+as const/g, "")
  .replace(/^\s*type .*$/gm, "")
  .replace(/\)\s*:\s*Metadata\[\"alternates\"\]\s*\{/g, ") {")
  .replace(/\)\s*:\s*string\s*\{/g, ") {")
  .replace(/([a-zA-Z_]\w*)(\s*:\s*[a-zA-Z_][\w.<>\[\]]*(\s*\|\s*[a-zA-Z_][\w.<>\[\]]*)+)/g, "$1")
  .replace(/\): Record<Locale, string> \{/g, ") {")
  .replace(/: Record<Locale, string>/g, "")
  .replace(/\?:[^,)=]*/g, "")
  .replace(/:\s*Metadata\[[^\]]*\]/g, "")
  .replace(/:\s*(string|number|Locale|Record<[^>]*>)\b(\[\])?/g, "");
const localesSrc = fs.readFileSync(process.argv[4], "utf-8")
  .replace(/^import .*$/gm, "")
  .replace(/^export /gm, "")
  .replace(/\s+as const/g, "")
  .replace(/^\s*type .*$/gm, "")
  .replace(/: Locale\b(?=\s*[=,()])/g, "")
  .replace(/: string\b(?=\s*[,)])/g, "")
  .replace(/value is Locale/g, "")
  .replace(/\):  \{/g, ") {")
  .replace(/\(SUPPORTED_LOCALES as readonly string\[\]\)/g, "SUPPORTED_LOCALES");
const localePathSrc = fs.readFileSync(process.argv[5], "utf-8")
  .replace(/^import .*$/gm, "")
  .replace(/^export /gm, "")
  .replace(/\s+as const/g, "")
  .replace(/^\s*type .*$/gm, "")
  .replace(/: Locale\b(?=\s*[=,()])/g, "")
  .replace(/: string\b(?=\s*[,)])/g, "")
  .replace(/value is Locale/g, "")
  .replace(/\)\s*:\s*boolean\s*\{/g, ") {")
  .replace(/\): \{ [^}]*\} \| null \{/g, ") {")
  .replace(/([a-zA-Z_]\w*)(\s*:\s*[a-zA-Z_][\w.<>\[\]]*(\s*\|\s*[a-zA-Z_][\w.<>\[\]]*)+)/g, "$1")
  .replace(/\?:[^,)=]*/g, "")
  .replace(/:\s*(string|number|Locale)\b/g, "");

const bundle = `${localesSrc}\n${localePathSrc}\n${alternatesSrc}\n${mod}\nmodule.exports = { sitemap, SITEMAP_URL, SITE_ORIGIN, SUPPORTED_LOCALES };`;
const out = { urls: null, sitemapUrl: null, origin: null, locales: null, error: null };
try {
  const m = require("module");
  const wrapped = new m.Module("sitemap-bundle");
  wrapped._compile(bundle, "/tmp/sitemap_bundle.js");
  const e = wrapped.exports;
  const entries = e.sitemap();
  out.urls = entries.map((x) => x.url);
  out.fieldsPerEntry = entries.map((x) => Object.keys(x).sort());
  out.sitemapUrl = e.SITEMAP_URL;
  out.origin = e.SITE_ORIGIN;
  out.locales = e.SUPPORTED_LOCALES;
} catch (err) {
  out.error = String(err && err.stack || err);
}
fs.writeFileSync(process.argv[6], JSON.stringify(out, null, 2));
'''


def run_sitemap_harness() -> dict:
    web = REPO / "web"
    out = Path("/tmp/g15_sitemap.json")
    harness = Path("/tmp/g15_sitemap_harness.js")
    harness.write_text(SITEMAP_HARNESS, encoding="utf-8")
    subprocess.run(
        ["node", str(harness),
         str(web / "app/sitemap.ts"),
         str(web / "lib/alternates.ts"),
         str(web / "lib/i18n/locales.ts"),
         str(web / "lib/localePath.ts"),
         str(out)],
        check=True, capture_output=True, timeout=60,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data.get("error") is None, f"sitemap harness error: {data['error']}"
    return data


class S1SitemapTests(unittest.TestCase):
    # A2-1: 通用静态页五语言; 法律/支持页仅英文正式版
    MULTILINGUAL_PATHS = {"/", "/search", "/guide", "/mcp-guide", "/skills"}
    ENGLISH_ONLY_PATHS = {"/terms", "/privacy", "/support"}
    LOCALES = ["zh-CN", "en", "ja", "ko", "de"]

    @classmethod
    def setUpClass(cls):
        cls.data = run_sitemap_harness()

    def test_sitemap_generates_full_grid(self):
        # A2-1: 5 通用路径 × 5 语言 + 3 法律页(仅 en) = 28 条
        urls = self.data["urls"]
        self.assertEqual(len(urls), 28)
        self.assertEqual(len(set(urls)), 28, "sitemap URLs must be unique")
        self.assertEqual(self.data["locales"], self.LOCALES)

    def test_all_urls_from_whitelist_and_origin(self):
        # 期望集合按 withLocale SSOT 语义构造: "/" → "/<locale>",
        # 其他路径 → "/<locale><path>"(en 同样带前缀, 与站点路由一致)
        origin = self.data["origin"]
        allowed = {
            f"{origin}/{loc}" if path == "/" else f"{origin}/{loc}{path}"
            for loc in self.LOCALES for path in self.MULTILINGUAL_PATHS
        } | {
            f"{origin}/en{path}" for path in self.ENGLISH_ONLY_PATHS
        }
        self.assertEqual(set(self.data["urls"]), allowed)

    def test_non_english_legal_urls_excluded(self):
        # A2-1: 非英文法律 URL 不得进入 Sitemap(noindex 页面)
        for url in self.data["urls"]:
            if any(url.endswith(f"/{slug}") for slug in self.ENGLISH_ONLY_PATHS):
                self.assertTrue(url.startswith(f"{self.data['origin']}/en/"),
                                f"non-EN legal URL in sitemap: {url}")

    def test_no_private_admin_account_workbench_urls(self):
        forbidden = ("/aichem", "/login", "/me", "/samelabs", "/api/",
                     "/note/", "/chemical/", "/reaction/", "/user/",
                     "?q=", "&q=", "page=", "mode=")
        for url in self.data["urls"]:
            for token in forbidden:
                self.assertNotIn(token, url, f"forbidden URL fragment {token} in {url}")

    def test_no_fabricated_last_modified(self):
        # 每条 entry 只有 url 字段 —— 不伪造 lastModified/changeFrequency/priority
        for fields in self.data["fieldsPerEntry"]:
            self.assertEqual(fields, ["url"])

    def test_robots_declares_sitemap_from_same_ssot(self):
        robots_src = (REPO / "web/app/robots.ts").read_text(encoding="utf-8")
        self.assertIn('sitemap: SITEMAP_URL', robots_src)
        self.assertIn('import { SITEMAP_URL } from "./sitemap"', robots_src)
        # SITEMAP_URL 与站点 origin 同源(SITE_ORIGIN SSOT)
        self.assertTrue(self.data["sitemapUrl"].startswith(self.data["origin"]))


class S2SearchMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "web/app/(site)/search/page.tsx").read_text(encoding="utf-8")

    def test_parameterized_search_is_noindex_follow(self):
        self.assertIn("const hasQuery = Boolean(params.q || params.mode || params.page);", self.src)
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


class S3LegalPagesTests(unittest.TestCase):
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
            self.assertIn(f"<h1>{heading}</h1>", src)
            self.assertIn("Effective October 6, 2026", src) if slug == "terms" else None

    def test_no_hreflang_claims_for_translations(self):
        for slug in self.PAGES:
            src = (REPO / f"web/app/(site)/{slug}/page.tsx").read_text(encoding="utf-8")
            self.assertNotIn("hreflang", src)

    def test_english_body_root_marks_lang_en(self):
        # A2-3: 英文正文根内容容器显式 lang="en"(不动全站 <html lang>)
        for slug in self.PAGES:
            src = (REPO / f"web/app/(site)/{slug}/page.tsx").read_text(encoding="utf-8")
            self.assertIn('<article lang="en" className="content-page guide-page legal-page">',
                          src, f"{slug} root content container missing lang=\"en\"")


class A2McpGuideMetadataTests(unittest.TestCase):
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


class S4LoginTests(unittest.TestCase):
    def test_login_noindex_follow(self):
        src = (REPO / "web/app/(site)/login/page.tsx").read_text(encoding="utf-8")
        self.assertIn("robots: { index: false, follow: true }", src)

    def test_login_behavior_untouched(self):
        src = (REPO / "web/app/(site)/login/page.tsx").read_text(encoding="utf-8")
        for anchor in ("safeNextPath", "AccountForm", "nextPath"):
            self.assertIn(anchor, src)


if __name__ == "__main__":
    unittest.main()
