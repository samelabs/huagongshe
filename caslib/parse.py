"""caslib.parse — ChemicalBook 中文 CAS 页/供应商页 解析(保序)。

页面结构(2026-08-25 实测, fixture: ~/ops/cb-fixtures/, 不入库):
- 正文区块由 <a data-name="X"></a> 锚点分隔, 顺序即页面顺序
- 基本信息: <div class="Basicsl"> 内 <div><span>键</span>值</div>
- KV 区(物理化学性质/安全数据): <div class="xztable"> 内
  <div class="xztr"><span>键</span>值</div>
- 散文区(应用领域/制备方法/常见问题/毒性防护/包装储运/安全特性/知名试剂):
  <div class="cwb"><div class="tbt">小标题</div><span>内容</span></div>
- 上下游: <div class="tyc"><div class="tbt">上游原料</div><a>名</a>...</div>
- 供应商(CAS页): <div class="gslist"> 条目
- 供应商专用页: <div class="supplier_list_li" data-cbsid="N"> 条目

输出 entry_cn 结构(保序):
{
  "basic": [[键,值],...],            # Basicsl 行(去掉 MOL 文件外链行)
  "aliases": {"cn": [...], "en": [...]},  # 中文别名/英文别名(BR 拆分)
  "props": [[键,值],...],            # 物理化学性质 xztr
  "safety": [[键,值],...],           # 安全数据 xztr
  "prose": [{"title","text"},...],   # 应用领域/制备方法/常见问题/毒性防护/包装储运/安全特性 各小节
  "updown": {"up": [...], "down": [...]},
  "reagents": [{"vendor","text"}],   # 知名试剂公司产品信息
}
supplier 结构: {ref,name,phone,email,website,purity,pack_price,remark}
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

from .redact import supplier_ref

# ---------------------------------------------------------------- 基础工具

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
_WS_RE = re.compile(r"\s+")
# 原站编辑署名句(实测出现在 prose 值内), 解析边界整体剔除
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


# ---------------------------------------------------------------- 区块切分

_ANCHOR_RE = re.compile(r'<a\s+data-name="([^"]+)"\s+data-id=', re.I)


def _blocks(html: str) -> dict[str, str]:
    """按正文锚点切分, 返回 {锚点名: 区块html}。后出现者覆盖前者(正文在锚点导航后)。"""
    out: dict[str, str] = {}
    anchors = [(m.start(), m.group(1)) for m in _ANCHOR_RE.finditer(html)]
    for idx, (pos, name) in enumerate(anchors):
        end = anchors[idx + 1][0] if idx + 1 < len(anchors) else len(html)
        out[name] = html[pos:end]
    return out


# ---------------------------------------------------------------- 基本信息

# Basicsl: <div><span>键</span> 值 </div>, 值内可能有 <em>
_BASIC_ROW_RE = re.compile(
    r"<div>\s*<span>([^<]+)</span>([\s\S]*?)</div>", re.I
)
_MOL_ROW_KEY = "MOL 文件"
# 安全特性/知名试剂等区块里的链接外链丢弃, 文本保留 → text_of 已做

# mol 外链(2026-08-28 实测锚点): Basicsl 内 <span>MOL 文件</span><a title="..MolFile" href="/CAS/mol/{cas}.mol">
# 只在"MOL 文件"行上下文内取站内绝对路径, 拒绝外域/散页误配
_MOL_HREF_RE = re.compile(
    r"<span>\s*MOL\s*文件\s*</span>\s*<a[^>]*href=[\"'](/CAS/mol/[^\"'?]+\.mol)[\"']",
    re.I,
)


def extract_mol_href(cas_html: str) -> str | None:
    """详情页 MOL 文件外链(站内路径), 无则 None。管制品/无结构条目无此前提。"""
    if not cas_html:
        return None
    m = _MOL_HREF_RE.search(cas_html)
    return m.group(1) if m else None


def _parse_basic(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for m in _BASIC_ROW_RE.finditer(block):
        key = text_of(m.group(1))
        val = text_of(m.group(2))
        if not key or key == _MOL_ROW_KEY:
            continue
        if val:
            rows.append([key, val])
    return rows


# ---------------------------------------------------------------- KV 区

_XZTR_RE = re.compile(r'<div class="xztr"><span>([^<]*)</span>([\s\S]*?)</div>')


def _parse_kv(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for m in _XZTR_RE.finditer(block):
        key = text_of(m.group(1))
        val = text_of(m.group(2))
        if key and val:
            rows.append([key, val])
    return rows


# ---------------------------------------------------------------- 散文区

_CWB_RE = re.compile(
    r'<div class="cwb">\s*<div class="tbt">(.*?)</div>\s*<span>([\s\S]*?)</span>',
    re.I | re.S,
)

# 纳入 prose 的锚点名(页面原生分区名, 保序)
_PROSE_SECTIONS = [
    "应用领域",
    "制备方法",
    "常见问题列表",
    "毒性防护",
    "包装储运",
    "安全特性毒性储运",
]
# 安全特性锚点名实际形态: "65-85-0(安全特性,毒性,储运)" — 按 data-upper 锚点集动态匹配
_PROSE_PAT = re.compile(
    r"^(应用领域|制备方法|常见问题列表|毒性防护|包装储运)|"
    r"^\d{2,7}-\d{2}-\d\(安全特性,毒性,储运\)$"
)


# ---------------------------------------------------------------- 上下游

_TYC_RE = re.compile(
    r'<div class="tyc">\s*<div class="tbt">(.*?)</div>([\s\S]*?)</div>', re.I | re.S
)


def _parse_updown(block: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in _TYC_RE.finditer(block):
        label = text_of(m.group(1))
        items = [
            t for t in (text_of(a) for a in re.findall(r"<a[^>]*>([\s\S]*?)</a>", m.group(2))) if t
        ]
        if label and items:
            key = "up" if "上游" in label else "down"
            out.setdefault(key, []).extend(items)
    return out


# ---------------------------------------------------------------- 知名试剂

_CWB_ALL_RE = re.compile(
    r'<div class="cwb">\s*<div class="tbt">(.*?)</div>\s*<span>([\s\S]*?)</span>\s*</div>',
    re.I,
)


def _extract_balanced_div(body: str, start_marker: str) -> str:
    """从 start_marker 起, 按 div 嵌套深度取平衡闭合的容器内容(含 marker)。"""
    i = body.find(start_marker)
    if i < 0:
        return ""
    depth = 0
    for m in re.finditer(r"<div\b|</div>", body[i:]):
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                return body[i : i + m.end()]
        else:
            depth += 1
    return ""


def _parse_reagents(block: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in _CWB_RE.finditer(block):
        vendor = text_of(m.group(1))
        lines = text_of(m.group(2), split_br=True)
        if vendor and lines:
            out.append({"vendor": vendor, "text": "；".join(lines)})
    return out


# ---------------------------------------------------------------- 别名

_TBT_SPAN_RE = re.compile(
    r'<div class="tbt">(.*?)</div>\s*<span>([\s\S]*?)</span>', re.I
)


def _parse_aliases(basic_block: str) -> dict[str, list[str]]:
    """中/英别名共处同一个 cwb 容器(实测形态), 平衡容器内逐对 tbt+span 提取。"""
    out: dict[str, list[str]] = {}
    idx = 0
    while True:
        i = basic_block.find('<div class="cwb">', idx)
        if i < 0:
            break
        container = _extract_balanced_div(basic_block[i:], '<div class="cwb">')
        if not container:
            break
        for m in _TBT_SPAN_RE.finditer(container):
            title = text_of(m.group(1))
            if title == "中文别名":
                vals = text_of(m.group(2), split_br=True)
                if vals:
                    out["cn"] = vals
            elif title == "英文别名":
                vals = text_of(m.group(2), split_br=True)
                if vals:
                    out["en"] = vals
        idx = i + len(container)
    return out


# ---------------------------------------------------------------- 供应商

# CAS 页 gslist 条目
_GSLIST_RE = re.compile(
    r'<div class="gslist">([\s\S]*?)(?=<div class="gslist">|<div class="pagebox"|$)'
)
_GSNAME_RE = re.compile(r'<div class="gsname">\s*<a[^>]*>([\s\S]*?)</a>', re.I)

_CPJS_ROW_RE = re.compile(r"<div><span>([^<]+)</span>([\s\S]*?)</div>", re.I)
# 供应商专用页条目
_SPL_RE = re.compile(
    r'<div class="supplier_list_li" data-cbsid="(\d+)">([\s\S]*?)'
    r"(?=<div class=\"supplier_list_li\"|<div class=\"pagebox\"|$)"
)


def _gsxx_fields(gslist_body: str) -> dict[str, str]:
    """gslist 条目内 gsxx 容器字段。容器嵌套 div, 必须平衡提取。"""
    fields: dict[str, str] = {}
    idx = 0
    while True:
        i = gslist_body.find('<div class="gsxx">', idx)
        if i < 0:
            break
        container = _extract_balanced_div(gslist_body[i:], '<div class="gsxx">')
        if not container:
            break
        sm = re.search(r"<span>([^<：:]+)[：:]</span>", container)
        if sm:
            label = text_of(sm.group(1))
            if label == "联系电话":
                # span 后到 cpjs/容器尾的纯文本
                rest = re.sub(r"<span>[^<]*</span>", "", container, count=1)
                v = text_of(re.sub(r'<div class="cpjs">[\s\S]*$', "", rest))
                if v:
                    fields["phone"] = v
            elif label == "产品介绍":
                inner = _extract_balanced_div(container, '<div class="cpjs">')
                if inner:
                    for rm in _CPJS_ROW_RE.finditer(inner):
                        k = text_of(rm.group(1)).rstrip("：:")
                        v = text_of(rm.group(2))
                        if not v:
                            continue
                        if k == "纯度":
                            fields["purity"] = v
                        elif k == "包装信息":
                            fields["pack_price"] = v
                        elif k == "备注":
                            fields["remark"] = v
        idx = i + len(container)
    return fields


def _parse_suppliers_cas_page(html: str) -> dict[str, dict[str, Any]]:
    """CAS 页 gslist 条目 -> {name: supplier}。产品介绍行齐全。"""
    out: dict[str, dict[str, Any]] = {}
    for m in _GSLIST_RE.finditer(html):
        body = m.group(1)
        nm = _GSNAME_RE.search(body)
        if not nm:
            continue
        name = text_of(nm.group(1))
        if not name:
            continue
        f = _gsxx_fields(body)
        sup: dict[str, Any] = {
            "ref": None,  # 专用页合并时回填
            "cbsid": None,  # CAS页无cbsid, 专用页合并时回填
            "name": name,
            # tag(黄金产品/现货/大货/新品)为原站付费推广位, 不入库不出解析层
            "phone": f.get("phone"),
            "email": None,
            "website": None,
            "purity": f.get("purity"),
            "pack_price": f.get("pack_price"),
            "remark": f.get("remark"),
        }
        out[name] = sup
    return out


def _spl_field(block: str, label: str) -> str | None:
    """专用页 framework_lp 字段: 平衡容器提取后剥标签前缀。"""
    idx = 0
    marker = '<div class="framework_lp">'
    while True:
        i = block.find(marker, idx)
        if i < 0:
            return None
        container = _extract_balanced_div(block[i:], marker)
        if not container:
            return None
        m = re.search(rf"<span>{re.escape(label)}[：:]</span>", container)
        if m:
            v = text_of(container[m.end() :])
            # 供应商无独立官网时"网址"填原站店铺页 — 整值丢弃
            if v and "chemicalbook" in v.lower():
                return None
            return v or None
        idx = i + len(container)


def _parse_suppliers_dedicated(html: str) -> dict[str, dict[str, Any]] | None:
    """供应商专用页 -> {name: {cbsid, email, website, phone}}。仅取联系增强字段。"""
    out: dict[str, dict[str, Any]] = {}
    for m in _SPL_RE.finditer(html):
        cbsid, body = m.group(1), m.group(2)
        nm = re.search(r'<div class="h_name">([\s\S]*?)</div>', body)
        if not nm:
            continue
        name = text_of(nm.group(1))
        if not name:
            continue
        fields: dict[str, Any] = {"cbsid": cbsid}
        phone = _spl_field(body, "联系电话")
        email = _spl_field(body, "电子邮件")
        website = _spl_field(body, "网址")
        if phone:
            fields["phone"] = phone
        if email:
            fields["email"] = email
        if website:
            fields["website"] = website
        out[name] = fields
    return out if out else None


def merge_suppliers(
    cas_page: dict[str, dict[str, Any]], dedicated: dict[str, dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """CAS 页 18 条为全集, 专用页按公司名合并 email/website; ref=cbsid 哈希。

    CAS 页无 cbsid, 专用页有。两页公司名一致(实测同一公司同名)。
    未出现在专用页的 CAS 页条目 ref 用名称哈希(保持稳定去重键)。
    """
    dedicated = dedicated or {}
    merged: list[dict[str, Any]] = []
    for name, sup in cas_page.items():
        extra = dedicated.pop(name, None)
        row = dict(sup)
        # cbsid: 原站供应商身份标识(DB身份列), ref: 不透明哈希(公开引用)。
        # 两者并存 — 边界: cbsid 只落DB, 任何API/DOM输出只用 ref。
        if extra:
            row["cbsid"] = extra.get("cbsid")
            row["phone"] = row["phone"] or extra.get("phone")
            row["email"] = extra.get("email")
            row["website"] = extra.get("website")
            if extra.get("cbsid"):
                row["ref"] = supplier_ref(extra["cbsid"])
        if not row["ref"]:
            row["ref"] = supplier_ref(f"name:{name}")
        merged.append(row)
    # 专用页独有条目( CAS 页被截断时兜底 )
    for name, extra in dedicated.items():
        merged.append(
            {
                "cbsid": extra.get("cbsid"),
                "ref": supplier_ref(extra["cbsid"]) if extra.get("cbsid") else supplier_ref(f"name:{name}"),
                "name": name,
                "phone": extra.get("phone"),
                "email": extra.get("email"),
                "website": extra.get("website"),
                "purity": None,
                "pack_price": None,
                "remark": None,
            }
        )
    return merged


# ---------------------------------------------------------------- 主入口

_NOT_FOUND_MARK = "本站不显示该产品信息"
_BASICSL_RE = re.compile(r'<div class="Basicsl">([\s\S]{0,3000}?)英文名称', re.I)


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


def parse_entry(html: str) -> dict[str, Any] | None:
    """中文 CAS 页 -> entry_cn。not_found/空页返回 None。"""
    if looks_like_not_found(html):
        return None
    blocks = _blocks(html)
    entry: dict[str, Any] = {}
    basic = blocks.get("基本信息", "")
    basic_rows = _parse_basic(_basicsl_slice(html))
    if basic_rows:
        entry["basic"] = basic_rows
    aliases = _parse_aliases(basic)
    if aliases:
        entry["aliases"] = aliases
    props = _parse_kv(blocks.get("物理化学性质", ""))
    if props:
        entry["props"] = props
    safety = _parse_kv(blocks.get("安全数据", ""))
    if safety:
        entry["safety"] = safety
    prose: list[dict[str, str]] = []
    for name, block in blocks.items():  # dict 保插入序 = 页面顺序
        if _PROSE_PAT.match(name):
            for cm in _CWB_RE.finditer(block):
                title = text_of(cm.group(1))
                text = text_of(cm.group(2))
                if title and text:
                    prose.append({"title": title, "text": text})
    if prose:
        entry["prose"] = prose
    updown = _parse_updown(blocks.get("上下游产品信息", ""))
    if updown:
        entry["updown"] = updown
    reagents = _parse_reagents(blocks.get("知名试剂公司产品信息", ""))
    if reagents:
        entry["reagents"] = reagents
    if not entry:
        return None
    return entry


def _basicsl_slice(html: str) -> str:
    i = html.find('<div class="Basicsl">')
    if i < 0:
        return ""
    # Basicsl 结束于 物理化学性质 锚点
    j = html.find('<a  data-name="物理化学性质"', i)
    if j < 0:
        j = html.find('data-name="物理化学性质"', i)
    if j < 0:
        j = i + 4000
    return html[i:j]


def parse_suppliers(cas_html: str, dedicated_html: str | None) -> list[dict[str, Any]]:
    """两页解析+合并。CAS 页无供应商区块时返回 []。"""
    cas_page = _parse_suppliers_cas_page(cas_html)
    if not cas_page:
        return []
    dedicated = _parse_suppliers_dedicated(dedicated_html) if dedicated_html else None
    return merge_suppliers(cas_page, dedicated)


def extract_cb_number(html: str) -> str | None:
    """从 CAS 页提取供应商专用页所需的 CB 编号 (ProdSupplierGNCB{N}.htm)。"""
    m = re.search(r'/ProdSupplierGNCB(\d+)\.htm', html)
    return m.group(1) if m else None
