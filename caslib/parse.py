"""caslib 页面解析(0905 收口后): 只保留三类职责 —
1. 文本工具: text_of / _balanced_table
2. CPP 页供应商表: parse_cpp_suppliers
3. 页面判定: cpp_page_state / page_identity / looks_like_not_found / extract_cb_number

旧 CAS 页 entry 解析(parse_entry/parse_cpp_entry/parse_cpp_entry_en/merge)
已随 0905 canonical schema 重构退役: 新解析器 = parse_cpp.parse_cpp_page。
试剂价格/全球分布/试剂用途区(reagent_prices/global_distribution/reagents)
确认为死数据不采, 相关函数一并剥除。
"""
from __future__ import annotations

import html as _html
import re
from typing import Any


_TAG_RE = re.compile(r"<[^>]+>")


_BR_RE = re.compile(r"<br\s*/?>", re.I)


_WS_RE = re.compile(r"\s+")


_EDITORIAL_RE = re.compile(r"本信息由[^。]*?(?:编辑整理|整理)[。；;]?")


def _decode(s: str) -> str:
    return _html.unescape(s)


def text_of(fragment: str, *, split_br: bool = False) -> str | list[str]:
    """HTML 片段 -> 纯文本。split_br=True 时按 <BR> 拆多值(别名等)。"""
    frag = fragment.strip()
    if split_br:
        parts = _BR_RE.split(frag)
        out = []
        for p in parts:
            t = _WS_RE.sub("", _decode(_TAG_RE.sub("", p))).strip()
            if t:
                out.append(t)
        return out
    t = _decode(_TAG_RE.sub("", frag))
    t = _EDITORIAL_RE.sub("", t)
    # 值内换行压缩为单空格 (KV 行与散文皆如此呈现)
    t = _WS_RE.sub(" ", t).strip()
    return t


_NOT_FOUND_MARK = "本站不显示该产品信息"


_BASICSL_RE = re.compile(r'<div class="Basicsl">([\s\S]{0,3000}?)英文名称', re.I)


_PAGE_IDENTITY_MARKS = (
    '<div class="Basicsl">',        # CAS 详情页结构壳(收录/未收录模板都有)
    'id="ChemicalProperties"',      # CPP 页属性表(CN 页)
    'id="GridView2"',               # CPP 语言页属性表(EN 实测, 201KB 真页无 ChemicalProperties)
)


_CB_LINK_RE = re.compile(
    r"/(?:ProdSupplierGN|ProductMSDSDetail|PriceInfoall_CB)CB\d+\.htm"
)


_CPP_DT_RE = re.compile(r"<dt[^>]*>\s*(?:CAS No\.?|CBNumber|MOL File)", re.I)


def page_identity(html: str | None) -> str:
    """真页面身份判定: 'real' | 'alien'。

    real  = 携带至少一种站内结构标记(Basicsl壳/ChemicalProperties表/cb链接)
    alien = 无任何站内结构 — 大拦截页(验证码/质询/改版壳), 不论字节多大,
            不具备 not_found 资格(error 语义, 走重试, 拦截事件可观测)。
    """
    if not html:
        return "alien"
    for mark in _PAGE_IDENTITY_MARKS:
        if mark in html:
            return "real"
    if _CB_LINK_RE.search(html):
        return "real"
    # CPP dt/dl 结构(语言页变体, 兜底标记)
    if _CPP_DT_RE.search(html):
        return "real"
    return "alien"


def looks_like_not_found(html: str) -> bool:
    """三种 not_found 形态:
    1. 明示拒绝(管制): "本站不显示该产品信息"
    2. 模板空页: 有 Basicsl 壳但无英文名称行(50-00-7/99999-99-9 实测形态)
    3. 无 Basicsl 容器
    """
    if _NOT_FOUND_MARK in html:
        return True
    if '<div class="Basicsl">' not in html:
        return True
    if not _BASICSL_RE.search(html):
        return True
    return False


def extract_cb_number(html: str) -> str | None:
    """CAS 页提取自身 CB 编号。

    主路径: GN 供应商链接 (ProdSupplierGNCB{N}.htm)。
    兜底(2026-08-28): 无供应商品目 GN 链接缺失时, MSDS/PriceInfo 链接同号
    (69-72-7 实测三链接同号 1680010)。
    """
    for pat in (r"/ProdSupplierGNCB(\d+)\.htm",
                r"/ProductMSDSDetailCB(\d+)\.htm",
                r"/PriceInfoall_CB(\d+)\.htm"):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


_CPP_SUP_ROW_RE = re.compile(
    r'<tr align="center"[^>]*>\s*<td>\s*<a\s+href=[\'"]https?://www\.chemicalbook\.com'
    r"/ShowSupplierProductsList(\d+)/0\.htm[\'\"][^>]*>([\s\S]*?)</a>\s*</td>([\s\S]*?)</tr>",
    re.I,
)


def parse_cpp_suppliers(html: str) -> list[dict[str, Any]]:
    """CPP-CN 页供应商表(一页全量, 热门品目100家封顶) -> [{cbsid,ref,name,phone,email,locale}]。

    六列: 供应商/联系电话/电子邮件/国家/产品数/优势度。
    locale=国家列原文(中国/德国/美国/日本/印度/欧洲/美洲...)。
    产品数/优势度(原站推广指标)不采。
    """
    out: list[dict[str, Any]] = []
    for m in _CPP_SUP_ROW_RE.finditer(html):
        cbsid, name_raw, rest = m.group(1), m.group(2), m.group(3)
        name = text_of(name_raw)
        if not name or not cbsid:
            continue
        cells = [
            text_of(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", rest, re.I)
        ]
        phone = cells[0] if len(cells) > 0 else ""
        email = cells[1] if len(cells) > 1 else ""
        locale = cells[2] if len(cells) > 2 else ""
        out.append(
            {
                "cbsid": cbsid,
                "ref": f"cb-supplier:{cbsid}",
                "name": name,
                "phone": phone or None,
                "email": email or None,
                "locale": locale or None,
            }
        )
    return out


_CPP_PAGE_MIN_BYTES = 10_000  # 真页实测 ≥12.8KB, 错误/降级页 <1KB, 中间零样本。


def cpp_page_state(html: str | None) -> str:
    """CPP 页判定: 大小分界 + 页面身份, 不做文本特征匹配。

    - <10KB: 系统错误/网络错误/质询降级 — 一律 error 语义, 走重试。
    - ≥10KB 且 real(站内结构在): 真页面 — ok(无变体由上层解析器判,
      解析空=无有效信息)
    - ≥10KB 但 alien(无任何站内结构): 大拦截页 — error 语义, 走重试。
    系统错误/网络错误留存记录(error), 不落数据层; not_found 只有真页面才有资格。
    """
    if html is None or len(html) < _CPP_PAGE_MIN_BYTES:
        return "error"
    if page_identity(html) != "real":
        return "error"
    return "ok"


def _balanced_table(html: str, start: int) -> tuple[int, int] | None:
    """嵌套表平衡计数: 外层 <table> 从 start 到配平 </table> 的区间。"""
    depth = 0
    for m in re.finditer(r"<table|</table>", html[start : start + 60000]):
        if m.group(0) == "<table":
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return start, start + m.end()
    return None
