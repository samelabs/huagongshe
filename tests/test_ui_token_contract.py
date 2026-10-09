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
6. No alert( / confirm( / prompt( calls in TSX.
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
]

# ── colors with no equal-value token in tokens.css — awaiting decision ───────
# (Step 1 report §5; later steps will either map them to status tokens or
# extend the scale. The strict test below stays expectedFailure meanwhile.)
KNOWN_HEX_PENDING: dict[str, set[str]] = {
    "app/globals.css": {
        "#22364d", "#0f1b2a", "#cfe3f7",              # .admin-pre 深色代码块
        "#16283c", "#101d2c", "#7fa3c9", "#b9c9dc",   # .admin-nav 深色侧栏
        "#8a6d00", "#e0c56e", "#fdf6e3",              # pipe 琥珀系（warn 近似但非等值）
        "#b33", "#e6b3b3", "#fdf0f0",                 # pipe 红系（err 近似但非等值）
        "#2e9e44", "#2e9e4488",                       # .pipe-dot.ok
        "#047857", "#a7f3d0", "#92400e", "#fde68a",   # .note-vis-badge
    },
}

# ── native-dialog violations owned by a later step (ConfirmDialog rollout) ──
KNOWN_DIALOG_CALLS: dict[str, str] = {
    "components/workbench/panels/NotesPanel.tsx": "window.confirm(",
    "components/ReactionOwnerActions.tsx": "window.confirm(",
}


def hex_findings(exclude_pending: bool) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    for p in scan_files():
        r = rel(p)
        pending = KNOWN_HEX_PENDING.get(r, set()) if exclude_pending else set()
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            hits = HEX_RE.findall(line)
            if not hits:
                continue
            if any(r == wf and content in line for wf, content, _ in HEX_LINE_WHITELIST):
                continue
            if pending and all(h in pending for h in hits):
                continue
            findings.append((r, i, line.strip()[:140]))
    return findings


def font_size_findings() -> list[tuple[str, int, str]]:
    # one fallback level is allowed: var(--wb-fs-sm, var(--fs-12))
    single = r"var\(--(wb-)?fs[a-z0-9-]*(?:, ?var\(--(wb-)?fs[a-z0-9-]*\))?\)"
    allowed = re.compile(rf"^(?:{single}|inherit|16px)$")
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

    def test_known_pending_hex_actually_present(self):
        for wf, hexes in KNOWN_HEX_PENDING.items():
            text = (WEB / wf).read_text(encoding="utf-8")
            for h in hexes:
                self.assertIn(h, text, f"pending hex {h} no longer occurs in {wf}: prune it")

    def test_no_color_literals_beyond_whitelist_and_pending(self):
        findings = hex_findings(exclude_pending=True)
        self.assertEqual([], findings, "new hex/rgb-literal style colors appeared")

    def test_no_rgb_or_hsl_function_literals(self):
        findings = []
        for p in scan_files():
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if "rgb(" in line or "hsl(" in line:
                    findings.append((rel(p), i, line.strip()[:140]))
        self.assertEqual([], findings)
        # NOTE: rgba() (box-shadow tints) is deliberately out of scope in Step 1;
        # DESIGN_SYSTEM §11.4 (shadow policy) owns it in a later step.

    @unittest.expectedFailure
    def test_no_hex_literals_at_all(self):
        # strict target: everything in KNOWN_HEX_PENDING is resolved by later steps
        self.assertEqual([], hex_findings(exclude_pending=False))


class FontSizeTests(unittest.TestCase):
    def test_only_violations_are_deferred_clamps(self):
        # guard: the expectedFailure test below may only fail on clamp() values;
        # any other off-scale font-size is a fresh regression and fails here
        for _f, _ln, value in font_size_findings():
            self.assertTrue(
                value.startswith("clamp("),
                f"non-clamp font-size violation: {_f}:{_ln} {value}",
            )

    @unittest.expectedFailure
    def test_font_size_takes_only_scale_tokens(self):
        # clamp() headlines are deferred to a later step (report §6)
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


class DialogCallTests(unittest.TestCase):
    def test_known_dialog_calls_still_present(self):
        # pin the exact set of known offenders so the guard below can't rot
        for wf, needle in KNOWN_DIALOG_CALLS.items():
            self.assertIn(needle, (WEB / wf).read_text(encoding="utf-8"),
                          f"known dialog call disappeared from {wf}: update both tests")

    def test_no_dialog_calls_beyond_known(self):
        findings = []
        for p in scan_files():
            if p.suffix != ".tsx":
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if any(tok in line for tok in ("alert(", "confirm(", "prompt(")):
                    findings.append((rel(p), i, line.strip()[:120]))
        known = {(f, KNOWN_DIALOG_CALLS[f]) for f in KNOWN_DIALOG_CALLS}
        fresh = [x for x in findings if not any(x[0] == kf and needle in x[2]
                                                for kf, needle in known)]
        self.assertEqual([], fresh, "new alert/confirm/prompt call appeared")

    @unittest.expectedFailure
    def test_no_dialog_calls_at_all(self):
        # strict target: ConfirmDialog (DESIGN_SYSTEM §6) replaces these later
        findings = []
        for p in scan_files():
            if p.suffix != ".tsx":
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if any(tok in line for tok in ("alert(", "confirm(", "prompt(")):
                    findings.append((rel(p), i, line.strip()[:120]))
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
