"""caslib.gwparse — CB 国际供应商页(ProdSupplierGWCB{cb}.htm) 解析。

页面形态(2026-08-28 实测 fixture: 65-85-0, 5家: 德国/日本/欧洲/美洲/美国):
- 每供应商一张 <tr> 表: 公司名称链接(含CBSID) / 联系电话 / 电子邮件 / 国籍 /
  产品介绍(英文名称+CAS+纯度/包装/备注 BR分行) / CB指数 / 网址
- CBSID 同时出现在公司链接前的 RecommendSupplier.aspx?CBSID={id} (块内多次, 同值)
- 无分页, 一页全量(与GN不同); 需 Referer 头才 200(裸拉 500)
"""
from __future__ import annotations

import html as _html
import re
from typing import Any

_ROW_FIELD_RE = re.compile(
    r'<td class="ProdGN_[13]">\s*(公司名称|联系电话|电子邮件|国籍|产品介绍|CB指数|网址)：?\s*</td>\s*'
    r'<td[^>]*>([\s\S]*?)</td>',
    re.I,
)
_COMPANY_LINK_RE = re.compile(
    r'<a[^>]*href="[^"]*"[^>]*>\s*([A-Za-z0-9][^<]{1,80}?)\s*</a>\s*(&nbsp;|<font|$)',
)
_CBSID_RE = re.compile(r"CBSID=(\d+)")


def _text(fragment: str) -> str:
    t = _html.unescape(re.sub(r"<[^>]+>", " ", fragment))
    return re.sub(r"\s+", " ", t).strip()


def parse_gw_suppliers(gw_html: str) -> list[dict[str, Any]]:
    """GW 页 -> 国际供应商列表。

    返回 [{"cbsid","name","nationality","phone","email","website","cb_index",
           "product_name_en","purity","pack_price","remark"}]; 字段缺失 None, 不抛。
    无身份键(cbsid)或公司名的块整块丢弃(宁缺勿错)。
    """
    if not gw_html or "国籍：" not in gw_html:
        return []
    # 按块切: 每 cbsid 出现的头部区域聚一块 — 以"公司名称行"为块首更稳
    # GW 页公司行无 <td> 标签形态, 统一按 CBSID 出现顺序分块
    marks = [m.start() for m in re.finditer(r"RecommendSupplier\.aspx\?CBSID=\d+", gw_html)]
    if not marks:
        return []
    # 块边界 = 当前 mark 到下一个公司链接出现处(下一个 mark 前约2500字符的公司行)
    blocks: list[str] = []
    starts: list[int] = []
    for i, pos in enumerate(marks):
        # 去重: 同一供应商块内 CBSID 出现多次(推荐/投诉/收藏)
        if starts and pos - starts[-1] < 500:
            continue
        starts.append(pos)
    for i, pos in enumerate(starts):
        # 块首回退到公司名链接(往前300), 块尾到下一块首
        block_start = max(0, pos - 400)
        block_end = starts[i + 1] - 400 if i + 1 < len(starts) else len(gw_html)
        blocks.append(gw_html[block_start:block_end])

    out: list[dict[str, Any]] = []
    for block in blocks:
        sid_m = _CBSID_RE.search(block)
        if not sid_m:
            continue
        cbsid = sid_m.group(1)
        # 公司名: 块首第一个非脚本链接的文本(排除 推荐/投诉/收藏/导航)
        name = None
        for lm in _COMPANY_LINK_RE.finditer(block):
            t = _text(lm.group(1))
            if t and t not in ("推荐", "投诉", "收藏", "产品目录", "全球销售网络", "用户评价") \
                    and not t.startswith("产品目录("):
                name = t
                break
        if not name:
            continue
        # 字段行
        fields: dict[str, str] = {}
        for fm in _ROW_FIELD_RE.finditer(block):
            fields[fm.group(1)] = _text(fm.group(2))
        if not fields:
            continue  # 公司在块里但没有表单字段=错切, 丢弃
        intro = fields.get("产品介绍", "")
        product_name_en = purity = pack_price = remark = None
        # 产品介绍是 _text 压扁后的 "英文名称：X CAS：Y 纯度：Z 包装信息：W 备注：R" 单行
        # (源码 BR 换行已被压成空格) — 按标签词切。
        for kw, setter in (
            ("英文名称：", "name_en"), ("纯度：", "purity"),
            ("包装信息：", "pack"), ("备注：", "remark"), ("CAS：", "_cas"),
        ):
            m = re.search(re.escape(kw) + r"\s*([^ ]+(?:\s(?!英文名称：|纯度：|包装信息：|备注：|CAS：)[^ ]+)*)", intro)
            if m:
                val = m.group(1).strip() or None
                if setter == "name_en":
                    product_name_en = val
                elif setter == "purity":
                    purity = val
                elif setter == "pack":
                    pack_price = val
                elif setter == "remark":
                    remark = val
        cb_index = None
        if fields.get("CB指数", "").isdigit():
            cb_index = int(fields["CB指数"])
        website = fields.get("网址") or None
        if website and "chemicalbook" in website.lower():
            website = None
        out.append({
            "cbsid": cbsid,
            "name": name,
            "nationality": fields.get("国籍") or None,
            "phone": fields.get("联系电话") or None,
            "email": fields.get("电子邮件") or None,
            "website": website,
            "cb_index": cb_index,
            "product_name_en": product_name_en,
            "purity": purity,
            "pack_price": pack_price,
            "remark": remark,
        })
    return out
