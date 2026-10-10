"""UI token contract for the v1.7 design-system rollout (docs/DESIGN_SYSTEM.md §11).

Step 1 scope: three parallel style-variable systems were converged onto
web/app/tokens.css. This module pins that convergence with pure static
source scans of web/app + web/components — no database, no network, no
node. Violations that exist *today* and are owned by later steps are
marked ``@unittest.expectedFailure`` and pinned by a companion guard so
they cannot silently grow; each is listed in the Step 1 report.

Checks:
1. No hex / rgb( / hsl( color literals outside tokens.css and an
   explicit file+line whitelist (data-driven colors, metadata literals).
   Colors with no equal-value token in tokens.css are parked in
   KNOWN_HEX_PENDING awaiting a decision (report §5) — the strict
   no-hex-at-all test stays expectedFailure until they are resolved.
2. font-size only takes var(--fs-*) / var(--wb-fs*) / inherit / 16px
   (input iOS-zoom guard). Today's only offenders are responsive
   clamp() headlines, deferred to a later step.
3. border-radius only takes var(--r-*) / var(--wb-r-*) / 999px / 50% /
   0 / inherit.
4. Every --wb-* in aichem-tokens.css is a pure alias — its value must
   start with var(--, no literals of its own.
5. --green* / --warm* tokens must not reappear.
6. No alert( / confirm( / prompt( calls in TSX. A bare ``confirm(``
   call is legal only in files that also call ``useConfirm`` — that is
   the ConfirmDialog API replacing the native dialogs (Step 4).
7. Brand: components/ui/HgsLogo.tsx geometry (polygon points, path d)
   must stay byte-identical to web/public/brand/*.svg source files.
8. Brand: public/brand/*.svg is the only place besides the line
   whitelist where hex values are allowed (brand source files).
9. Entity display: no HCID/HRID display may be spelled (interpolating
   an id) outside components/ui/EntityBadge.tsx. The i18n dictionaries
   (lib/i18n/locales, not scanned) and aria-only copy are exempt;
   EntityBadge keeps its literals behind the component boundary.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
SCAN_DIRS = ("app", "components")
SUFFIXES = (".css", ".tsx")

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FONT_SIZE_RE = re.compile(r"font-size\s*:\s*([^;{}]+)[;}]", re.I)
RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;{}]+)[;}]", re.I)
WB_DEF_RE = re.compile(r"(--wb-[a-z0-9-]+)\s*:\s*([^;]+);")


def scan_files() -> list[Path]:
    out: list[Path] = []
    for sub in SCAN_DIRS:
        for p in (WEB / sub).rglob("*"):
            if p.suffix in SUFFIXES and p.name != "tokens.css":
                out.append(p)
    return sorted(out)


def rel(p: Path) -> str:
    return str(p.relative_to(WEB))


# ── §11.1 whitelist: file + exact line-content match, never whole files ──────
HEX_LINE_WHITELIST: list[tuple[str, str, str]] = [
    # metadata 只接受字符串字面量，无法引用 CSS 变量；值与 tokens.css --brand 一致
    ("app/layout.tsx", 'themeColor: "#1e90ff"',
     "viewport metadata literal; mirrors --brand"),
    # 分类颜色是数据（读写数据库，喂给 <input type="color">，只认 hex 字面量）
    ("components/samelabs/SkillsAdminPanel.tsx", 'color: "#1e90ff"',
     "category color form default; DB-bound data, input[type=color] needs a hex"),
    # HgsLogo 的白色横画随 hgs-mark.svg 源文件逐字交付（§7 geometry 契约的组成部分）
    ("components/ui/HgsLogo.tsx", '<g fill="#FFFFFF">',
     "brand mark knockout white, byte-identical to public/brand/hgs-mark.svg"),
]

# ── §2 brand: public/brand/*.svg 是品牌源文件, 色值是其交付物的一部分 ─────────
# 文件级白名单: 目录里新增 SVG 必须显式登记在这里(双向钉死, 防止借目录夹带)。
HEX_FILE_WHITELIST: dict[str, str] = {
    "public/brand/hgs-mark.svg": "品牌图形标源文件(blue-500 + 白色横画)",
    "public/brand/hgs-mark-on-dark.svg": "深色底图形标源文件(blue-400)",
    "public/brand/hgs-mark-line.svg": "线框图形标源文件(currentColor)",
    "public/brand/hgs-mark-16.svg": "16px 简化版图形标源文件",
    "public/brand/hgs-wordmark.svg": "字标源文件(currentColor)",
    "public/brand/hgs-lockup.svg": "横版组合源文件(静态场景)",
    "public/brand/hgs-app-icon.svg": "App 图标源文件(渐变例外见 DESIGN_SYSTEM §2.2)",
}


def brand_svg_files() -> list[Path]:
    return sorted((WEB / "public" / "brand").glob("*.svg"))


def hex_scan_files() -> list[Path]:
    # hex/rgb/hsl 扫描覆盖面 = 组件样式 + 品牌 SVG 源文件(后者整体在文件白名单里)
    return scan_files() + brand_svg_files()

# ── native-dialog ban (DESIGN_SYSTEM §11.7) ─────────────────────────────
# ConfirmDialog (Step 4) replaces window.confirm; its hook returns a
# function named ``confirm``, so a bare ``confirm(`` is legal only in
# files that also call ``useConfirm``. window.alert/confirm/prompt and
# bare alert(/prompt( have no legitimate producer and are always banned.
DIALOG_RE = re.compile(r"(?<![.\w])(alert|confirm|prompt)\s*\(")
WINDOW_DIALOG_RE = re.compile(r"window\.(alert|confirm|prompt)\s*\(")
CONFIRM_HOOK = "useConfirm("


def dialog_findings() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for p in scan_files():
        if p.suffix != ".tsx":
            continue
        text = p.read_text(encoding="utf-8")
        has_hook = CONFIRM_HOOK in text
        for i, line in enumerate(text.splitlines(), 1):
            if WINDOW_DIALOG_RE.search(line):
                findings.append((rel(p), i, line.strip()[:120]))
                continue
            m = DIALOG_RE.search(line)
            if m and not (m.group(1) == "confirm" and has_hook):
                findings.append((rel(p), i, line.strip()[:120]))
    return findings


def hex_findings() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for p in hex_scan_files():
        r = rel(p)
        if r in HEX_FILE_WHITELIST:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            hits = HEX_RE.findall(line)
            if not hits:
                continue
            if any(r == wf and content in line for wf, content, _ in HEX_LINE_WHITELIST):
                continue
            findings.append((r, i, line.strip()[:140]))
    return findings


def font_size_findings() -> list[tuple[str, int, str]]:
    # allowed: var(--fs-*) (optionally with a one-level token fallback),
    # inherit, the 16px input iOS-zoom guard, and a responsive clamp whose
    # BOTH ends are var(--fs-*) tokens (middle term free, e.g. 3.5vw)
    single = r"var\(--(wb-)?fs[a-z0-9-]*(?:, ?var\(--(wb-)?fs[a-z0-9-]*\))?\)"
    clamp = rf"clamp\(var\(--fs-[a-z0-9-]+\), [^,]+, var\(--fs-[a-z0-9-]+\)\)"
    allowed = re.compile(rf"^(?:{single}|{clamp}|inherit|16px)$")
    findings: list[tuple[str, int, str]] = []
    for p in scan_files():
        if p.suffix != ".css":
            continue
        text = p.read_text(encoding="utf-8")
        for m in FONT_SIZE_RE.finditer(text):
            value = m.group(1).strip()
            if not allowed.match(value):
                line_no = text.count("\n", 0, m.start()) + 1
                findings.append((rel(p), line_no, value))
    return findings


def radius_findings() -> list[tuple[str, int, str]]:
    allowed = re.compile(r"^(var\(--(wb-)?r[a-z0-9-]*\)|999px|50%|0|0px|inherit)$")
    findings: list[tuple[str, int, str]] = []
    for p in scan_files():
        if p.suffix != ".css":
            continue
        text = p.read_text(encoding="utf-8")
        for m in RADIUS_RE.finditer(text):
            value = m.group(1).strip()
            for part in value.split():
                if not allowed.match(part):
                    line_no = text.count("\n", 0, m.start()) + 1
                    findings.append((rel(p), line_no, value))
                    break
    return findings


class ColorLiteralTests(unittest.TestCase):
    def test_whitelist_entries_still_match(self):
        # a whitelist entry whose file/line vanished is stale and must be pruned
        for wf, content, _why in HEX_LINE_WHITELIST:
            path = WEB / wf
            self.assertTrue(path.exists(), f"whitelist file missing: {wf}")
            self.assertTrue(
                any(content in ln for ln in path.read_text(encoding="utf-8").splitlines()),
                f"stale whitelist entry: {wf}: {content}",
            )

    def test_no_hex_literals_beyond_whitelist(self):
        findings = hex_findings()
        self.assertEqual([], findings, "hex color literal outside the file+line whitelist")

    def test_no_rgb_or_hsl_function_literals(self):
        findings = []
        for p in hex_scan_files():
            if rel(p) in HEX_FILE_WHITELIST:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if "rgb(" in line or "hsl(" in line:
                    findings.append((rel(p), i, line.strip()[:140]))
        self.assertEqual([], findings)
        # NOTE: rgba() (box-shadow tints) is deliberately out of scope in Step 1;
        # DESIGN_SYSTEM §11.4 (shadow policy) owns it in a later step.



class FontSizeTests(unittest.TestCase):
    def test_font_size_takes_only_scale_tokens(self):
        # var(--fs-*) (+fallback) / token-to-token clamp / inherit / 16px input guard
        self.assertEqual([], font_size_findings())


class BorderRadiusTests(unittest.TestCase):
    def test_radius_takes_only_scale_tokens(self):
        self.assertEqual([], radius_findings())


class WorkbenchAliasTests(unittest.TestCase):
    def test_wb_tokens_are_pure_aliases(self):
        path = WEB / "app/(workbench)/aichem-tokens.css"
        text = path.read_text(encoding="utf-8")
        defs = WB_DEF_RE.findall(text)
        self.assertGreater(len(defs), 50, "alias block unexpectedly small")
        bad = [(name, value.strip()) for name, value in defs
               if not value.strip().startswith("var(--")]
        self.assertEqual([], bad, "--wb-* values must all alias tokens.css vars")

    def test_tokens_css_imported_before_globals(self):
        text = (WEB / "app/layout.tsx").read_text(encoding="utf-8")
        self.assertLess(
            text.index('import "./tokens.css"'),
            text.index('import "./globals.css"'),
        )


class ForbiddenTokenTests(unittest.TestCase):
    def test_no_green_or_warm_tokens(self):
        for p in scan_files():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                self.assertNotRegex(
                    line, r"--(green|warm)[a-z-]*\s*:",
                    f"{rel(p)}:{i} redefines a deleted --green*/--warm* token",
                )
                self.assertNotIn(
                    "var(--green", line, f"{rel(p)}:{i} uses deleted --green* token")
                self.assertNotIn(
                    "var(--warm", line, f"{rel(p)}:{i} uses deleted --warm* token")


class BrandAssetTests(unittest.TestCase):
    """DESIGN_SYSTEM §2: React 实现的 SVG geometry 与品牌源文件逐字一致。"""

    def test_hgs_logo_geometry_matches_brand_svgs(self):
        logo = (WEB / "components" / "ui" / "HgsLogo.tsx").read_text(encoding="utf-8")
        mark = (WEB / "public" / "brand" / "hgs-mark.svg").read_text(encoding="utf-8")
        wordmark = (WEB / "public" / "brand" / "hgs-wordmark.svg").read_text(encoding="utf-8")
        # 图形标: polygon points 逐字照抄
        for pts in re.findall(r'<polygon points="([^"]+)"', mark):
            self.assertIn(f'points="{pts}"', logo,
                          f"HgsLogo mark polygon diverged from hgs-mark.svg: {pts}")
        # 字标: path d 逐字照抄
        for d in re.findall(r'<path d="([^"]+)"', wordmark):
            self.assertIn(f'd="{d}"', logo,
                          f"HgsLogo wordmark path diverged from hgs-wordmark.svg: {d}")

    def test_brand_svg_hex_whitelist_is_exact(self):
        # 双向钉死: public/brand 下每个 svg 都登记在白名单里(新文件必须显式登记),
        # 白名单里每个条目都真实存在(删源文件必须同步删条目)。
        on_disk = {rel(p) for p in brand_svg_files()}
        listed = set(HEX_FILE_WHITELIST)
        self.assertEqual(
            listed, on_disk,
            f"brand svg whitelist out of sync: only-on-disk={sorted(on_disk - listed)}, "
            f"only-in-whitelist={sorted(listed - on_disk)}")

    def test_brand_whitelist_entries_exist(self):
        for wf in HEX_FILE_WHITELIST:
            self.assertTrue((WEB / wf).exists(), f"brand whitelist file missing: {wf}")


class DialogCallTests(unittest.TestCase):
    def test_no_dialog_calls_at_all(self):
        # DESIGN_SYSTEM §11.7：alert/confirm/prompt 一律禁止；
        # 唯一例外是 useConfirm() 返回的 confirm({...})（ConfirmDialog API）。
        self.assertEqual([], dialog_findings())


# ── entity display spelled outside EntityBadge (DESIGN_SYSTEM §11.8) ──────
ENTITY_BADGE_FILE = "components/ui/EntityBadge.tsx"
# HCID/HRID 后面紧跟 id 插值 = 在拼写实体号的展示（模板串或 JSX 文本）
ENTITY_SPELL_RE = re.compile(r"(HCID|HRID)(\s*\$\{|\s*\{[a-zA-Z_.\[\]]+\})")


def entity_spell_findings() -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for p in scan_files():
        if p.suffix != ".tsx" or rel(p) == ENTITY_BADGE_FILE:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if ENTITY_SPELL_RE.search(line):
                findings.append((rel(p), i, line.strip()[:120]))
    return findings


class EntityBadgeDisplayTests(unittest.TestCase):
    def test_no_entity_id_spelled_outside_badge(self):
        # 字典(lib/i18n/locales，不在扫描面)与纯 aria 文案(无插值)不在此列；
        # support 页等处的散文提及(“包含 HCID 或 HRID”)没有 id 插值，不算展示。
        self.assertEqual([], entity_spell_findings())


if __name__ == "__main__":
    unittest.main()
