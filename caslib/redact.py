"""caslib.redact — 去标识边界。

解析产物在离开 caslib 之前必须过本模块:
- CBSID -> 不透明 ref (sha256 前16hex)
- 丢弃 CB 号、原站品牌/URL
下游(DB/API/前端/日志) 永不接触原站标识。
"""
from __future__ import annotations

import hashlib


def supplier_ref(cbsid: str | int) -> str:
    """CBSID -> 不透明供应商引用 (与 DB cas_suppliers.ref 同算法)。"""
    return hashlib.sha256(f"hgs-cas-supplier:{cbsid}".encode()).hexdigest()[:16]


def scrub_text(text: str) -> str:
    """通用文本清洗: 实体解码由 parse 做, 这里只做防御性品牌词剔除。

    目前解析层已按字段白名单提取, 不从整页文本中捞内容,
    故此函数仅用于显式剥离可能混入字段值的原站 URL。
    """
    if not text:
        return text
    # 任何 chemicalbook 域名残留(字段值里几乎不可能有, 防御性兜底)
    for token in ("chemicalbook.com", "www.chemicalbook"):
        if token in text.lower():
            return ""
    return text
