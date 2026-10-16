"""样式字面值棘轮 —— 以基线为界,只许减少、不许新增。

版式层的取值从未被规范约束（间距/字重/行高/z-index/断点/容器宽/前缀各自
为政）。本模块把"当前存量"固化为基线清单：

- 存量值允许继续存在（迁移时逐步从基线删除,直到清零）；
- 任何不在基线里的新字面值或新样式前缀,测试直接失败 —— 新代码只能用
  tokens.css 的设计 token,或显式修基线（须给出理由）；
- rgba() 颜色不再豁免,与 hex 同样入册;
- 卡片 box-shadow 只允许浮层阴影 token 与焦点环两种形态,存量例外逐一
  登记(打印媒介与旧卡面阴影待版式迁移时移除)。

用法:
    python -m unittest tests.test_style_ratchet        # 检查(CI 同路径)
    python tests/style_ratchet.py --regen              # 重新生成基线(删存量后)
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
BASELINE = Path(__file__).resolve().parent / "style_ratchet_baseline.json"

SPACING_PROPS = (
    "padding", "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin", "margin-top", "margin-right", "margin-bottom", "margin-left",
    "gap", "row-gap", "column-margin", "row-margin", "inset", "top", "right",
    "bottom", "left",
)
WIDTH_PROPS = ("width", "min-width", "max-width")
DECL_RE = re.compile(r"(?:^|[;{])\s*(-?[a-z-]+)\s*:\s*([^;{}]+?)\s*(?=[;{}])", re.M)
PX_RE = re.compile(r"(-?\d+(?:\.\d+)?)px\b")
RGBA_RE = re.compile(r"rgba?\(\s*\d[\d\s,./%]*\)")
MEDIA_RE = re.compile(r"@media[^{]+")
MEDIA_W_RE = re.compile(r"(?:min|max)-width:\s*(\d+)px")
CLASS_RE = re.compile(r"\.([a-zA-Z][\w-]*)")
TSX_STYLE_PX_RE = re.compile(r'style=\{\{[^}]*?(\d+(?:\.\d+)?)px')

# box-shadow 允许形态: 浮层 token / 焦点环(3/4px 光晕) / 无阴影
SHADOW_FLOAT_RE = re.compile(r"^var\(--shadow-float\)$")
SHADOW_FOCUS_RE = re.compile(r"^0 0 0 [34]px var\(--(?:focus-halo|wb-glow)\)$")
SHADOW_NONE_RE = re.compile(r"^none$")


def _css_files() -> list[Path]:
    out: list[Path] = []
    for sub in ("app", "components"):
        for p in (WEB / sub).rglob("*.css"):
            if not p.name.endswith("tokens.css"):
                out.append(p)
    return sorted(out)


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*[\s\S]*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _prefix_of(class_name: str) -> str:
    return class_name.partition("-")[0] + "-" if "-" in class_name else class_name


def scan() -> dict[str, Counter]:
    """全量扫描,返回 每类别 -> 取值计数。"""
    counts: dict[str, Counter] = {
        "spacing_px": Counter(), "font_weight": Counter(), "line_height": Counter(),
        "z_index": Counter(), "breakpoint_px": Counter(), "width_px": Counter(),
        "rgba": Counter(), "prefixes": Counter(), "tsx_style_px": Counter(),
        "box_shadow_offenders": Counter(),
    }
    for p in _css_files():
        rel = str(p.relative_to(REPO))
        text = _strip_comments(p.read_text(encoding="utf-8"))
        for m in MEDIA_RE.finditer(text):
            for w in MEDIA_W_RE.findall(m.group(0)):
                counts["breakpoint_px"][w] += 1
        for m in DECL_RE.finditer(text):
            prop, value = m.group(1), m.group(2).strip()
            if prop in SPACING_PROPS:
                for v in PX_RE.findall(value):
                    counts["spacing_px"][v] += 1
            elif prop in WIDTH_PROPS:
                for v in PX_RE.findall(value):
                    counts["width_px"][v] += 1
            elif prop == "font-weight":
                for v in re.findall(r"\b\d{3}\b", value):
                    counts["font_weight"][v] += 1
            elif prop == "line-height":
                for v in re.findall(r"\d+(?:\.\d+)?", value.split("px")[0] + ("px" if "px" in value else "")):
                    counts["line_height"][v + ("px" if "px" in value else "")] += 1
            elif prop == "z-index":
                for v in re.findall(r"-?\d+", value):
                    counts["z_index"][v] += 1
            elif prop == "box-shadow":
                norm = re.sub(r"\s+", " ", value)
                if not (SHADOW_FLOAT_RE.match(norm) or SHADOW_FOCUS_RE.match(norm)
                        or SHADOW_NONE_RE.match(norm)):
                    counts["box_shadow_offenders"][f"{rel} :: {norm}"] += 1
            if prop != "box-shadow":
                for v in RGBA_RE.findall(value):
                    counts["rgba"][re.sub(r"\s+", "", v)] += 1
        for name in CLASS_RE.findall(text):
            counts["prefixes"][_prefix_of(name)] += 1
    for sub in ("app", "components"):
        for p in (WEB / sub).rglob("*.tsx"):
            for v in TSX_STYLE_PX_RE.findall(p.read_text(encoding="utf-8")):
                counts["tsx_style_px"][v] += 1
    return counts


def check() -> list[str]:
    """与基线对账,返回违规清单(空 = 通过)。"""
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    current = scan()
    offenders: list[str] = []
    for category, counter in current.items():
        allowed = set(baseline.get(category, {}))
        for value, n in sorted(counter.items()):
            if value not in allowed:
                where = "样式前缀" if category == "prefixes" else "字面值"
                offenders.append(
                    f"[{category}] 新增{where} {value!r} ×{n} —— 用 tokens.css 的设计 "
                    f"token 替代; 确属新档位则先更新 tests/style_ratchet_baseline.json "
                    f"并在评审说明理由")
    return offenders


def regen() -> None:
    current = scan()
    data = {k: dict(sorted(v.items(), key=lambda kv: (len(kv[0]), kv[0])))
            for k, v in current.items()}
    BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                        encoding="utf-8")
    total = sum(sum(v.values()) for v in data.values())
    print(f"baseline written: {BASELINE}")
    for k, v in data.items():
        print(f"  {k}: {len(v)} 取值 / {sum(v.values())} 处")
    print(f"  total: {total} 处")


if __name__ == "__main__":
    if "--regen" in sys.argv:
        regen()
    else:
        issues = check()
        print("\n".join(issues) or "style ratchet: OK")
        sys.exit(1 if issues else 0)
