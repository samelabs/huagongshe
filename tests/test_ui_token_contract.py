"""UI token contract for the v2.0 design-system rollout (docs/DESIGN_SYSTEM.md 第七章).

Static source scans of web/app + web/components — no database, no network, no
node. Checks:
1. No hex / rgb( / hsl( color literals outside tokens.css and an
   explicit file+line whitelist (data-driven colors, metadata literals).
2. font-size only takes scale tokens / inherit / 16px iOS-zoom guard.
3. border-radius only takes scale tokens / 999px / 50% / 0 / inherit.
4. Every --wb-* in aichem-tokens.css is a pure alias of tokens.css vars.
5. --green* / --warm* tokens must not reappear.
6. No alert( / confirm( / prompt( calls in TSX (ConfirmDialog via useConfirm).
7. Brand: components/ui/HgsLogo.tsx geometry byte-identical to SVG sources.
8. Brand: public/brand/*.svg only hex exceptions beyond line whitelist.
9. Entity display: no HCID/HRID display spelled outside EntityBadge.
10. EntityBadge: compact only in table columns or dev-ui showcase.
11. Form: all <form> tags must declare method="post".
12. Topbar: no search input or shortcut.
13. Media query: must not hide .hg-btn or its svg.
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


# ── 7.1 whitelist: file + exact line-content match, never whole files ──────
HEX_LINE_WHITELIST: list[tuple[str, str, str]] = [
    # metadata 只接受字符串字面量，无法引用 CSS 变量；值与 tokens.css --brand 一致
    ("app/layout.tsx", 'themeColor: "#1e90ff"',
     "viewport metadata literal; mirrors --brand"),
    # 分类颜色是数据（读写数据库，喂给 <input type="color">，只认 hex 字面量）
    ("components/samelabs/SkillsAdminPanel.tsx", 'color: "#1e90ff"',
     "category color form default; DB-bound data, input[type=color] needs a hex"),
    # HgsLogo 的白色横画随 hgs-mark.svg 源文件逐字交付（品牌 geometry 契约的组成部分）
    ("components/ui/HgsLogo.tsx", '<g fill="#FFFFFF">',
     "brand mark knockout white, byte-identical to public/brand/hgs-mark.svg"),
]

# ── 2.2 brand: public/brand/*.svg 是品牌源文件, 色值是其交付物的一部分 ─────────
# 文件级白名单: 目录里新增 SVG 必须显式登记在这里(双向钉死, 防止借目录夹带)。
HEX_FILE_WHITELIST: dict[str, str] = {
    "public/brand/hgs-mark.svg": "品牌图形标源文件(blue-500 + 白色横画)",
    "public/brand/hgs-mark-on-dark.svg": "深色底图形标源文件(blue-400)",
    "public/brand/hgs-mark-line.svg": "线框图形标源文件(currentColor)",
    "public/brand/hgs-mark-16.svg": "16px 简化版图形标源文件",
    "public/brand/hgs-wordmark.svg": "字标源文件(currentColor)",
    "public/brand/hgs-lockup.svg": "横版组合源文件(静态场景)",
    "public/brand/hgs-app-icon.svg": "App 图标源文件(渐变例外见 DESIGN_SYSTEM 2.2)",
}


def brand_svg_files() -> list[Path]:
    return sorted((WEB / "public" / "brand").glob("*.svg"))


def hex_scan_files() -> list[Path]:
    # hex/rgb/hsl 扫描覆盖面 = 组件样式 + 品牌 SVG 源文件(后者整体在文件白名单里)
    return scan_files() + brand_svg_files()

# ── native-dialog ban (DESIGN_SYSTEM 7.5) ─────────────────────────────
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
        # DESIGN_SYSTEM 7.3 (shadow policy) owns it in a later step.



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
        text = path.read_text(encoding="utf8")
        defs = WB_DEF_RE.findall(text)
        # 下限是防整个别名块被误清的哨兵；删除无引用的别名不受此限
        self.assertGreater(len(defs), 45, "alias block unexpectedly small")
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
    """DESIGN_SYSTEM 2.2: React 实现的 SVG geometry 与品牌源文件逐字一致。"""

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
        # DESIGN_SYSTEM 7.5：alert/confirm/prompt 一律禁止；
        # 唯一例外是 useConfirm() 返回的 confirm({...})（ConfirmDialog API）。
        self.assertEqual([], dialog_findings())


# ── entity display spelled outside EntityBadge (DESIGN_SYSTEM 7.6) ──────
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


# ── 7.7–7.8 BX-B1/B2: 旧类名清零 + ui 之外无原生表单元素 + eyebrow 禁止 ────
# 迁移终点（BX）：旧类名（button/wb-btn/empty-state/eyebrow/text-link/text-button）
# 的样式定义与使用全部清除；原生表单元素只允许出现在 components/ui 与下方
# 行级白名单（每条注明理由，禁止整文件豁免）。

LEGACY_CLASS_ATTR_RE = re.compile(
    r"""(?:class|className)\s*=\s*["'][^"']*\b(wb-btn|empty-state|eyebrow|text-link|text-button)\b""")
LEGACY_BUTTON_CLASS_ATTR_RE = re.compile(
    r"""(?:class|className)\s*=\s*["'][^"']*(?<![\w-])button(?![\w-])[^"']*["']""")

def _css_class_def(name: str) -> re.Pattern:
    return re.compile(r"(?<![\w-])\." + name + r"(?![\w-])")

NATIVE_FORM_RE = re.compile(r"<(button|input|select|textarea)\b")

# 行级白名单: (relpath, 行内必须包含的子串, 理由)
NATIVE_FORM_WHITELIST: list[tuple[str, str, str]] = [
    ("app/(site)/dev-ui/page.tsx", '<button type="button">撤销</button>',
     "dev 预览页 Toast 撤销钮的静态结构演示：production 构建下 404，非产品界面"),
    ("components/workbench/panels/SkillsPanel.tsx", 'type="file"',
     "文件上传 input：必须原生（按钮触发 ref.click()，ui Input 无 file 语义）"),
    ("components/samelabs/WorkersPanel.tsx", 'type="checkbox"',
     "复选框：ui 无 Checkbox 原语，浏览器原生勾选框外观"),
    ("components/samelabs/SkillsAdminPanel.tsx", 'type="color"',
     "取色器：ui 无 ColorPicker 原语，input[type=color] 原生色板"),
    ("components/shell/SiteHeader.tsx", "triggerRef",
     "头像/更多菜单触发器：焦点管理需 ref（ui Button 不转发 ref），sh-menu 键盘体系自有"),
    ("components/shell/SiteHeader.tsx", "sh-menu-logout",
     "菜单项行按钮：ui 无 Menu 原语，菜单行自有样式体系"),
    ("components/workbench/WbMobileNav.tsx", "wb-drawer-logout",
     "手机抽屉底部登出钮：与 SiteHeader sh-menu-logout 同为菜单行按钮（useLogout 共用实现）"),
    ("components/workbench/WbCreateMenu.tsx", "triggerRef",
     "「+ 新建」菜单触发器：焦点管理需 ref（ui Button 不转发 ref）"),
    ("components/workbench/EntityReferencePicker.tsx", "key={`c-${chemical.id}`}",
     "组合框选项行：ui 无 Option 原语，选项行自有样式"),
    ("components/workbench/EntityReferencePicker.tsx", "key={`r-${reaction.id}`}",
     "组合框选项行：ui 无 Option 原语，选项行自有样式"),
    ("components/workbench/EntityReferencePicker.tsx", 'onClick={() => remove("chemical", id)}',
     "已选实体 chip：ui 无可关闭 Chip 原语"),
    ("components/workbench/EntityReferencePicker.tsx", 'onClick={() => remove("reaction", id)}',
     "已选实体 chip：ui 无可关闭 Chip 原语"),
    ("components/workbench/panels/StoichPanel.tsx", "wb-stoich",
     "投料计算器紧凑网格（6.7）：单元格级密度需求，hg-input 标准控件尺寸会破坏表格布局；含 radio（ui 无 Radio 原语）"),
    ("components/PrintButton.tsx", 'className="pr-btn"',
     "打印报告工具栏按钮：打印页自有报告版式（pr-btn），不进 hg-btn 体系"),
    ("components/SearchHero.tsx", "inputRef",
     "首页大搜索框内层 input：srch-box-wrap 提供边框/焦点体系，内层必须裸置"),
]


class LegacyClassNameTests(unittest.TestCase):
    """BX-B1/B2 ①：六类旧类名（class 属性使用 + CSS 定义）全部清零。"""

    def test_no_legacy_class_attributes(self):
        offenders = []
        for p in scan_files():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if LEGACY_CLASS_ATTR_RE.search(line):
                    offenders.append(f"{rel(p)}:{i}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_legacy_class_css_definitions(self):
        offenders = []
        for p in scan_files():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                for name in ("wb-btn", "empty-state", "eyebrow", "text-link", "text-button"):
                    if _css_class_def(name).search(line):
                        offenders.append(f"{rel(p)}:{i}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_no_bare_button_class_attribute(self):
        """旧 `.button` 类族（BX-B1 盘点第 7 类）同样清零 —— 按钮统一 .hg-btn。"""
        offenders = []
        for p in scan_files():
            if p.suffix != ".tsx":
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if LEGACY_BUTTON_CLASS_ATTR_RE.search(line):
                    offenders.append(f"{rel(p)}:{i}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "\n".join(offenders))


class NativeFormElementTests(unittest.TestCase):
    """BX-B1/B2 ②：components/ui 之外不允许原生 button/input/select/textarea，
    行级白名单除外（每条注明理由）。"""

    def test_no_native_form_elements_outside_ui(self):
        offenders = []
        for p in scan_files():
            if p.suffix != ".tsx" or "components/ui" in rel(p):
                continue
            rel_path = rel(p)
            lines = p.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines, 1):
                if not NATIVE_FORM_RE.search(line):
                    continue
                # 标签与属性常分行（最多隔两行）—— 以「本行 + 后两行」窗口匹配白名单锚点
                window = "\n".join([line] + lines[i:i + 2])
                if any(rel_path == rel_f and needle in window for rel_f, needle, _ in NATIVE_FORM_WHITELIST):
                    continue
                offenders.append(f"{rel_path}:{i}: {line.strip()[:90]}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_whitelist_entries_actually_exist(self):
        """白名单必须钉住真实存在的行 —— 防止迁移后白名单悄悄过期。"""
        for rel_f, needle, _reason in NATIVE_FORM_WHITELIST:
            path = WEB / rel_f
            self.assertTrue(path.exists(), f"白名单文件不存在: {rel_f}")
            content = path.read_text(encoding="utf-8")
            self.assertIn(needle, content, f"白名单锚点失效: {rel_f} :: {needle}")


class EyebrowBanTests(unittest.TestCase):
    """BX-B1/B2 ③：eyebrow（英文大写 kicker）独立成条禁止 —— 分区标题就是 h2。"""

    def test_no_eyebrow_class_anywhere(self):
        offenders = []
        for p in scan_files():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"""(?:class|className)\s*=\s*["'][^"']*\beyebrow\b""", line):
                    offenders.append(f"{rel(p)}:{i}")
                if _css_class_def("eyebrow").search(line):
                    offenders.append(f"{rel(p)}:{i} (css)")
        self.assertEqual(offenders, [], "\n".join(offenders))


# ── Rule 6: compact only in table columns (DESIGN_SYSTEM 3.4 / 7.6) ────────
COMPACT_BADGE_RE = re.compile(r"<EntityBadge\b[^>]*\bcompact\b")


class CompactBadgeTests(unittest.TestCase):
    """DESIGN_SYSTEM 3.4 / 7.6: `compact`（只有字形和编号）只用于表格列，其他地方一律用完整徽标。"""

    def test_compact_badge_only_in_table_columns_or_dev(self):
        offenders = []
        for p in scan_files():
            if p.suffix != ".tsx":
                continue
            r = rel(p)
            if r == ENTITY_BADGE_FILE or r == "app/(site)/dev-ui/page.tsx":
                continue
            text = p.read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if COMPACT_BADGE_RE.search(line):
                    offenders.append(f"{r}:{i}: {line.strip()[:100]}")
        self.assertEqual([], offenders, "EntityBadge compact used outside table columns")


# ── Rule 9: form must declare method="post" (DESIGN_SYSTEM 4.3 / 7.9) ─────
FORM_TAG_RE = re.compile(r"<form\b([^>]*)>", re.DOTALL)
METHOD_POST_RE = re.compile(r'method=["\'{](?:post|POST)["\'}]')


class FormMethodPostTests(unittest.TestCase):
    """DESIGN_SYSTEM 4.3 / 7.9: 所有表单声明 method="post"。"""

    def test_all_forms_declare_method_post(self):
        offenders = []
        for p in scan_files():
            if p.suffix != ".tsx":
                continue
            r = rel(p)
            text = p.read_text(encoding="utf-8")
            for m in FORM_TAG_RE.finditer(text):
                tag_attrs = m.group(1)
                if not METHOD_POST_RE.search(tag_attrs):
                    line_no = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{r}:{line_no}: <form {tag_attrs.strip()[:80]}>")
        self.assertEqual([], offenders, "Form tag missing method=\"post\"")


# ── Rule 10: topbar has no search input (DESIGN_SYSTEM 2.3 / 7.10) ──────────
class TopbarSearchBanTests(unittest.TestCase):
    """DESIGN_SYSTEM 2.3 / 7.10: 顶栏无搜索输入框、无快捷键。"""

    def test_site_header_has_no_search_input(self):
        path = WEB / "components" / "shell" / "SiteHeader.tsx"
        self.assertTrue(path.exists(), "SiteHeader.tsx missing")
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("<input", text, "SiteHeader must not render native input")
        self.assertNotIn("HeaderSearch", text, "SiteHeader must not render HeaderSearch")
        self.assertNotIn("⌘K", text, "SiteHeader must not render ⌘K shortcut")
        self.assertNotIn("handleShortcut", text, "SiteHeader must not have search shortcut handler")


# ── Rule 11: media queries must not hide .hg-btn or its svg (DESIGN_SYSTEM 7.11) ─
HG_BTN_HIDE_RE = re.compile(r"([^{}]*\.hg-btn[^{}]*)\{\s*([^}]*display\s*:\s*none[^}]*)\}", re.DOTALL | re.I)


class MediaQueryButtonPreservationTests(unittest.TestCase):
    """DESIGN_SYSTEM 7.11: 在媒体查询里隐藏按钮的图标或操作（display: none 作用于 .hg-btn 或其 svg）。"""

    def test_no_media_query_hiding_button_or_svg(self):
        offenders = []
        for p in scan_files():
            if p.suffix != ".css":
                continue
            r = rel(p)
            text = p.read_text(encoding="utf-8")
            for m in re.finditer(r"@media\s*([^{]+)\{", text):
                start = m.end()
                depth = 1
                end = start
                while end < len(text) and depth > 0:
                    if text[end] == '{':
                        depth += 1
                    elif text[end] == '}':
                        depth -= 1
                    end += 1
                media_content = text[start:end - 1]
                for rule_m in HG_BTN_HIDE_RE.finditer(media_content):
                    selector = rule_m.group(1).strip()
                    body = rule_m.group(2).strip()
                    line_no = text.count("\n", 0, start + rule_m.start()) + 1
                    offenders.append(f"{r}:{line_no}: {selector} {{ {body} }}")
        self.assertEqual([], offenders, "Media query must not hide .hg-btn or its svg")


if __name__ == "__main__":
    unittest.main()

