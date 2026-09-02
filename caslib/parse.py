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

# mol 外链(2026-08-28 实测锚点; 0901 修正: CB 路径带日期段 /CAS/{YYYYMMDD}/mol/):
# Basicsl 内 <span>MOL 文件</span><a title="..MolFile" href="/CAS/20180703/mol/{cas}.mol">
# 旧形态 /CAS/mol/{cas}.mol 仍兼容。只在"MOL 文件"行上下文内取站内绝对路径, 拒绝外域/散页误配
# 0902: 标签兼容 MOL文件/MOL File(Mol文件), 单双引号均吃。
_MOL_HREF_RE = re.compile(
    r"<span>\s*MOL\s*(?:文件|File|file)\s*</span>\s*<a[^>]*href=[\"']"
    r"(/[^\"'?]+\.mol)[\"']",
    re.I,
)
# 0902 GPT审计: CPP 页 dt/dd 形态(<dt>MOL File:</dt><dd><a href='...mol'>,
# CB38154098 实测)。与 CAS 页 span 形态并存, 路径白名单一致。
_MOL_HREF_CPP_RE = re.compile(
    r"<dt>\s*MOL\s*File:?\s*</dt>\s*<dd>\s*<a[^>]*href=[\"']"
    r"(/[^\"'?]+\.mol)[\"']",
    re.I,
)


def extract_mol_href(cas_html: str) -> str | None:
    """详情页/CPP页 MOL 文件外链(站内路径), 无则 None。管制品/无结构条目无此前提。"""
    if not cas_html:
        return None
    m = _MOL_HREF_RE.search(cas_html) or _MOL_HREF_CPP_RE.search(cas_html)
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

# 安全特性锚点名实际形态: "65-85-0(安全特性,毒性,储运)" — 按 data-upper 锚点集动态匹配
_PROSE_PAT = re.compile(
    r"^(应用领域|制备方法|常见问题列表|毒性防护|包装储运)|"
    r"^\d{2,7}-\d{2}-\d\(安全特性,毒性,储运\)$"
)


# ---------------------------------------------------------------- 上下游

_TYC_RE = re.compile(
    r'<div class="tyc">\s*<div class="tbt">(.*?)</div>([\s\S]*?)</div>', re.I | re.S
)


# 上下游条目里的供应商导航链接(0902): CB 页下游区尾部挂"XXX国内生产厂家"
# 供应商导航链接, 非化学品 — 过滤(实测污染 7447 行, 全为该尾缀, 无其他变体)。
_UPDOWN_NAV_RE = re.compile(r"生产厂家$")


def _clean_updown_names(names: list[str]) -> list[str]:
    return [n for n in names if not _UPDOWN_NAV_RE.search(n)]


def _parse_updown(block: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in _TYC_RE.finditer(block):
        label = text_of(m.group(1))
        items = _clean_updown_names([
            t for t in (text_of(a) for a in re.findall(r"<a[^>]*>([\s\S]*?)</a>", m.group(2))) if t
        ])
        if label and items:
            key = "up" if "上游" in label else "down"
            out.setdefault(key, []).extend(items)
    return out


# ---------------------------------------------------------------- 知名试剂


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
_GSNAME_RE = re.compile(
    r'<div class="gsname">\s*<a href="([^"]+)"[^>]*>([\s\S]*?)</a>', re.I
)


def _gsname_supplier_id(href: str) -> str | None:
    """CAS 页供应商链接 URL 自带原站供应商ID: /ShowSupplierProductsList{id}/。

    实测与专用页 data-cbsid 同值(65-85-0: 18链接全有ID, 专用页8条为其一致子集)。
    这是 cbsid 的主取路径 — 专用页只是二跳增强, 覆盖不了 CAS 页全量。
    """
    m = re.search(r"/ShowSupplierProductsList(\d+)/", href or "")
    return m.group(1) if m else None

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
        name = text_of(nm.group(2))
        if not name:
            continue
        f = _gsxx_fields(body)
        # cbsid 主路径: CAS 页链接 URL 自带供应商ID(实测18/18覆盖)
        cbsid = _gsname_supplier_id(nm.group(1))
        sup: dict[str, Any] = {
            "ref": supplier_ref(cbsid) if cbsid else None,  # 无ID时名称哈希兜底
            "cbsid": cbsid,
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
        # cbsid 主路径=CAS页链接ID; 专用页 data-cbsid 同值(实测一致),
        # 仅在 CAS 页缺失时兜底回填, 不做覆盖(防两页错配时写错身份)。
        if extra:
            if not row.get("cbsid") and extra.get("cbsid"):
                row["cbsid"] = extra.get("cbsid")
                row["ref"] = supplier_ref(extra["cbsid"])
            row["phone"] = row["phone"] or extra.get("phone")
            row["email"] = extra.get("email")
            row["website"] = extra.get("website")
            if extra.get("cbsid") and not row.get("ref"):
                row["ref"] = supplier_ref(extra["cbsid"])
        if not row["ref"]:
            row["ref"] = supplier_ref(f"cbsid:{row['cbsid']}") if row.get("cbsid") else supplier_ref(f"name:{name}")
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


# ---- 页面身份标记(0902 判定总览 Q2): 真页面必有站内结构, 拦截页/验证码无 ----
# 三标记全无 = 不是真页面(不论字节多大) → error 语义。站内结构锚, 非文本关键词。
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


# ---------------------------------------------------------------- CPP 页解析
# ChemicalProductProperty_{L}_CB{cb}.htm (2026-08-28 实测, NBS CB2234049 fixture):
# CN页: 供应商一页全量100家表 + 试剂级价格表 + 全球分布统计 + 与CAS页同源entry区块
# EN页: th/td 属性表(含 InChI/SMILES/LogP 等英文独有字段)

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
                "ref": supplier_ref(cbsid),
                "name": name,
                "phone": phone or None,
                "email": email or None,
                "locale": locale or None,
            }
        )
    return out


_CPP_TR_RE = re.compile(r"<tr[^>]*>([\s\S]*?)</tr>", re.I)


def parse_cpp_reagent_prices(html: str) -> list[dict[str, str]]:
    """CN 页"试剂级价格"表 -> [{updated, code, name, package, price}]。

    表列: 更新日期/产品编号/产品名称/CAS编号/包装/价格。CAS编号恒为本品目,不存。
    行判据: 首列含日期斜杠。整行取td后按位取列。
    """
    i = html.find("产品编号")
    if i < 0:
        return []
    seg = html[i : i + 25000]
    out: list[dict[str, str]] = []
    for m in _CPP_TR_RE.finditer(seg):
        tds = [text_of(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", m.group(1), re.I)]
        if len(tds) >= 6 and "/" in tds[0] and tds[1]:
            out.append(
                {
                    "updated": tds[0],
                    "code": tds[1],
                    "name": tds[2],
                    "package": tds[4],
                    "price": tds[5],
                }
            )
    return out


_CPP_GLOBAL_RE = re.compile(r"全球有\s*(\d+)家供应商")


def parse_cpp_global_distribution(html: str) -> dict[str, Any] | None:
    """CN 页生产厂家区全球分布 -> {"total": N, "countries": {国家: 数量}}。缺失 None。"""
    m = _CPP_GLOBAL_RE.search(html)
    if not m:
        return None
    seg = html[m.start() : m.start() + 1500]
    text = text_of(re.sub(r"<[^>]+>", " ", seg))
    pairs = re.findall(r"([\u4e00-\u9fff]{2,4})\s*(\d+)", text)
    countries: dict[str, int] = {}
    for k, v in pairs:
        if k in ("全球有",):
            continue
        countries[k] = int(v)
    return {"total": int(m.group(1)), "countries": countries} if countries else None


_CPP_KV_RE = re.compile(
    r"<th[^>]*>([\s\S]*?)</th>\s*<td[^>]*>([\s\S]*?)</td>", re.I
)


def parse_cpp_entry_en(html: str) -> dict[str, Any] | None:
    """CPP-EN 页属性表 -> {"attributes": [[key, value],...]}(保序去重)。空值自然过滤。"""
    out: list[list[str]] = []
    for m in _CPP_KV_RE.finditer(html):
        key = text_of(m.group(1))
        val = text_of(m.group(2))
        if key and val:
            out.append([key, val])
    seen: set[str] = set()
    attrs = [kv for kv in out if not (kv[0] in seen or seen.add(kv[0]))]
    return {"attributes": attrs} if attrs else None


# ---------------------------------------------------------------- CPP-CN entry
# CPP 页结构与 CAS 页完全不同构(2026-08-28 实测, NBS CB2234049):
# basic: 页首 <dl><dt>键:</dt><dd>值</dd></dl>(每对独立dl, 值内<dd>未闭合畸形标记)
# props: <table id="ChemicalProperties"> 内 dt(<span>键:</span>)/dd(<span>值</span>)
# safety: SafetyInformation 外层表(嵌套内表每行一对 th/td, 14对) — 平衡计数取外层
# prose: <h3>标题</h3> 区块; updown: 上游原料/下游产品 h3 区
# 输出与 CAS 页 entry 同构(basic/aliases/props/safety/prose/updown) + 两个增量段
# (reagent_prices/global_distribution), 前端消费零改。

_CPP_PAGE_MIN_BYTES = 10_000  # 真页实测 ≥12.8KB, 错误/降级页 <1KB, 中间零样本。
# 0902 用户口径: <10KB 一律 error(系统/网络/质询错误, 留记录走重试);
# ≥10KB 才是真页面 — 解析不出内容 = not_found(占位页), 判定单点在大小。
# 0902 判定总览(Q2): 大页还需过 page_identity — 无站内结构的大拦截页
# (验证码/质询壳可达数十KB)仍判 error, 不给 not_found 资格。


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
_CPP_SKIP_DT = {"CBNumber", "MOL File"}


def _cpp_dd_value(rest: str) -> str:
    """dd 值: 截到 </dd> 或下一块标记(原站 <dd> 未闭合, 防越界吞并后续行)。"""
    stop = re.search(r"</dd>|<dt|<dl>|</table>|<tr", rest)
    seg = rest[: stop.start()] if stop else rest
    return text_of(seg)


def _cpp_kv_pairs(html: str) -> list[list[str]]:
    out: list[list[str]] = []
    for m in re.finditer(r"<dt[^>]*>([\s\S]*?)</dt>\s*<dd[^>]*>", html, re.I):
        key = text_of(m.group(1)).rstrip(":：").strip()
        val = _cpp_dd_value(html[m.end() : m.end() + 2000])
        if key and val and key not in _CPP_SKIP_DT:
            out.append([key, val])
    return out


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


def parse_cpp_entry(html: str) -> dict[str, Any] | None:
    """CPP-CN 页 -> entry。解析不出内容返回 None(调用方落 not_found)。

    页面有效性由 cpp_page_state() 前置判定(0902: <10KB 一律 error),
    本函数不做文本特征判断 — 拼接不出内容 = 无有效信息。
    """
    if not html:
        return None
    entry: dict[str, Any] = {}
    m_tbl = re.search(r'<table id="ChemicalProperties"', html, re.I)
    head = html[: m_tbl.start()] if m_tbl else html[:30000]
    basic = _cpp_kv_pairs(head)
    if basic:
        entry["basic"] = basic
        aliases: dict[str, list[str]] = {}
        for k, v in basic:
            if k in ("中文别名", "英文别名"):
                parts = [p.strip() for p in re.split(r"[;；]", v) if p.strip()]
                if parts:
                    aliases["cn" if k == "中文别名" else "en"] = parts
        if aliases:
            entry["aliases"] = aliases
    if m_tbl:
        tbl_end = html.find("</table>", m_tbl.start())
        props = _cpp_kv_pairs(html[m_tbl.start() : tbl_end])
        if props:
            entry["props"] = props
    sm = re.search(r'SafetyInformation[^>]*cellspacing', html)
    if sm:
        start = html.rfind("<table", 0, sm.start())
        span = _balanced_table(html, start) if start >= 0 else None
        if span:
            pairs = re.findall(
                r"<th[^>]*>([\s\S]*?)</th>\s*<td[^>]*>([\s\S]*?)</td>",
                html[span[0] : span[1]], re.I,
            )
            safety = [[text_of(k).rstrip(":：").strip(), text_of(v)] for k, v in pairs]
            safety = [kv for kv in safety if kv[0] and kv[1]]
            if safety:
                entry["safety"] = safety
    prose: list[dict[str, str]] = []
    for m3 in re.finditer(r"<h3[^>]*>([\s\S]*?)</h3>", html):
        title = text_of(m3.group(1))
        if not title or title in ("上游原料", "下游产品"):
            continue
        rest = html[m3.end() : m3.end() + 3000]
        stop = re.search(r"<h[23][^>]*>|<table|<dl>", rest)
        seg = rest[: stop.start()] if stop else rest
        text = text_of(seg)
        if text and len(text) > 4:
            prose.append({"title": title, "text": text})
    if prose:
        entry["prose"] = prose
    updown: dict[str, list[str]] = {}
    for label, key in (("上游原料", "up"), ("下游产品", "down")):
        lm = re.search(rf"<h3[^>]*>\s*{label}\s*</h3>([\s\S]*?)<(?:h3|table)", html)
        if lm:
            names = _clean_updown_names([
                text_of(a)
                for a in re.findall(r"<a[^>]*>([\s\S]*?)</a>", lm.group(1))
                if text_of(a)
            ])
            if names:
                updown[key] = names
    if updown:
        entry["updown"] = updown
    prices = parse_cpp_reagent_prices(html)
    if prices:
        entry["reagent_prices"] = prices
    gd = parse_cpp_global_distribution(html)
    if gd:
        entry["global_distribution"] = gd
    return entry or None
