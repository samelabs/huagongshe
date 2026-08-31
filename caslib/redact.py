"""caslib.redact — 去标识边界。

解析产物在离开 caslib 之前必须过本模块:
- CBSID -> 不透明 ref (sha256 前16hex); cbsid 原值随供应商字典保留(DB身份列)
- CB 号随 FetchResult.cb_number 保留(DB身份列)
- 丢弃原站品牌/URL
边界口径(2026-08-28 用户定案): 原站标识(cbsid/cb_number)落 DB 作身份字段,
但任何 API/DOM 输出零标识 — 公开引用一律用 ref 哈希。
"""
from __future__ import annotations

import hashlib


def supplier_ref(cbsid: str | int) -> str:
    """CBSID -> 不透明供应商引用 (与 DB cas_suppliers.ref 同算法)。"""
    return hashlib.sha256(f"hgs-cas-supplier:{cbsid}".encode()).hexdigest()[:16]


