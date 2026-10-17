"""对外数据服务的检索: 标识符与名称的候选查询, 以及未收录 CAS/SMILES
按站内同样规则建行并触发采集。

不做子结构和相似度检索。
"""

from __future__ import annotations

import asyncio
from typing import Any

from ...chemistry import CAS_RE, canonicalize_smiles, cas_checkdigit_valid
from ..cb import cas_search_state, enqueue_cas_search_fetch
from ..chemicals import fetch_chemicals, CHEMICAL_SELECT
from ..name_index import normalize_name
from .projections import resolve_title

LOOKUP_MAX = 20
FUZZY_MIN_CHARS = 3


class DataApiInvalidParameter(Exception):
    """入参不合法(错误码 invalid_parameter)。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _match(label: str, rows: list[dict[str, Any]], locale: str) -> list[dict[str, Any]]:
    candidates = []
    for row in rows:
        title, _ = resolve_title(row, locale)
        candidates.append({"hcid": row["id"], "title": title, "match": label})
    return candidates[:LOOKUP_MAX]


async def _by_ids(db: Any, ids: list[int], locale: str, label: str) -> list[dict[str, Any]]:
    from sqlalchemy import text as _text

    if not ids:
        return []
    rows = await fetch_chemicals(db, f"""
        SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c
        WHERE c.id = ANY(:ids) ORDER BY c.id
    """, {"ids": ids[:LOOKUP_MAX]}, locale=locale)
    return _match(label, rows, locale)


async def lookup(
    db: Any, *, locale: str,
    hcid: int | None = None, cas: str | None = None, smiles: str | None = None,
    inchikey: str | None = None, name: str | None = None,
    allow_ingest: bool = False,
) -> dict[str, Any]:
    """按唯一标识或名称查候选。

    未收录的兜底按 allow_ingest 分级：True 时与站内同一规则（SMILES
    建行、CAS 入列采集）；False（只读凭证默认）纯读 —— CAS 只查既有
    采集状态、SMILES 直接 not_found，不发生任何写库。
    """
    from sqlalchemy import text

    if cas is not None:
        cas = cas.strip()
        if not CAS_RE.fullmatch(cas) or not cas_checkdigit_valid(cas):
            raise DataApiInvalidParameter("CAS 号格式或校验位不正确")
        rows = await fetch_chemicals(db, f"""
            SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c
            WHERE c.cas_numbers @> ARRAY[:cas] ORDER BY c.id LIMIT :n
        """, {"cas": cas, "n": LOOKUP_MAX}, locale=locale)
        if rows:
            return {"candidates": _match("cas", rows, locale), "pending": None}
        # 未收录: 与站内搜索同一规则 —— 受控入列采集, 不建占位行。
        # 只读凭证不写库: 仅查询既有采集状态, 从不入列。
        state = await cas_search_state(db, cas)
        if state == "new" and allow_ingest:
            enqueued, _status, _row = await enqueue_cas_search_fetch(db, cas_number=cas)
            await db.commit()
            state = "pending" if enqueued else "miss"
        return {"candidates": [],
                "pending": {"cas": cas, "status": "updating" if state == "pending" else "not_found"}}

    if smiles is not None:
        # RDKit 解析/canonicalize 是 CPU 计算, 丢线程池避免卡事件循环
        # (与站内 search.py 的 canonicalize、resolve_or_create_chemical
        # 的 chemical_properties 同款处理)。
        canonical = await asyncio.to_thread(canonicalize_smiles, smiles.strip())
        if not canonical:
            raise DataApiInvalidParameter("SMILES 无法解析")
        rows = await fetch_chemicals(db, f"""
            SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c
            WHERE c.smiles = :smiles AND c.mol IS NOT NULL ORDER BY c.id LIMIT :n
        """, {"smiles": canonical, "n": LOOKUP_MAX}, locale=locale)
        if rows:
            return {"candidates": _match("smiles", rows, locale), "pending": None}
        if not allow_ingest:
            # 只读凭证: 未收录即 not_found, 不建行不采集
            return {"candidates": [],
                    "pending": {"smiles": canonical, "status": "not_found"}}
        # 未收录: 与站内同一规则 —— 本地建行(结构三件)并触发采集; 身份
        # 冲突/歧义时按站内口径不建行。
        from ..reactions import UnresolvedIdentityError, resolve_or_create_chemical
        try:
            chemical_id, _created = await resolve_or_create_chemical(db, canonical)
            await db.commit()
        except UnresolvedIdentityError as exc:
            raise DataApiInvalidParameter("该 SMILES 存在身份冲突，暂不能建行") from exc
        rows = await fetch_chemicals(db, f"""
            SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c WHERE c.id = :id
        """, {"id": chemical_id}, locale=locale)
        candidates = _match("smiles", rows, locale)
        for item in candidates:
            item["data_status"] = "updating"
        return {"candidates": candidates, "pending": None}

    if inchikey is not None:
        inchikey = inchikey.strip()
        rows = await fetch_chemicals(db, f"""
            SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c
            WHERE c.inchikey = :ik ORDER BY c.id LIMIT :n
        """, {"ik": inchikey, "n": LOOKUP_MAX}, locale=locale)
        return {"candidates": _match("inchikey", rows, locale), "pending": None}

    if hcid is not None:
        if hcid <= 0:
            raise DataApiInvalidParameter("HCID 必须是正整数")
        rows = await fetch_chemicals(db, f"""
            SELECT {CHEMICAL_SELECT} FROM chemistry.chemicals c
            WHERE c.id = :id
        """, {"id": hcid}, locale=locale)
        return {"candidates": _match("hcid", rows, locale), "pending": None}

    if name is not None:
        query = name.strip()
        if not query:
            raise DataApiInvalidParameter("名称不能为空")
        nq = normalize_name(query)
        # 名称精确等值: 各语言名称平等参与(name_index 镜像全部语言)。
        ids = (await db.execute(_text("""
            (SELECT c.id FROM chemistry.chemicals c
              WHERE lower(c.preferred_name) = lower(:q) OR lower(c.iupac_name) = lower(:q)
              ORDER BY c.id LIMIT :n)
            UNION
            (SELECT chemical_id FROM chemistry.name_index
              WHERE normalized = :nq ORDER BY chemical_id LIMIT :n)
            ORDER BY 1 LIMIT :n
        """), {"q": query, "nq": nq, "n": LOOKUP_MAX})).scalars().all()
        label = "name"
        if not ids:
            if len(nq) < FUZZY_MIN_CHARS:
                return {"candidates": [], "pending": None}
            ids = (await db.execute(_text("""
                SELECT DISTINCT chemical_id FROM chemistry.name_index
                WHERE normalized LIKE '%' || :nq || '%'
                ORDER BY chemical_id LIMIT :n
            """), {"nq": nq, "n": LOOKUP_MAX})).scalars().all()
            label = "name_contains"
        return {"candidates": await _by_ids(db, list(ids), locale, label), "pending": None}

    raise DataApiInvalidParameter("须提供 hcid / cas / smiles / inchikey / name 之一")
