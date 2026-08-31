"""name_index 摄入: 唯一写入方, 全量替换语义。

name_index 是纯派生镜像:
- source='cb'      镜像 chemical_cb.entry(中文名称/别名) + chemical_supplier.name
- source='pubchem' 镜像 chemicals.synonyms

每次摄入按 (chemical_id, source) 删旧插新, 无独立状态, 与源表永不漂移。
排除与该化合物 preferred_name/iupac_name normalize 相同的名字(避免与
主表两列重复; 主表两列已有自己的检索路径)。
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text

_WS_RE = re.compile(r"\s+")


def normalize_name(value: str) -> str:
    return _WS_RE.sub(" ", value.strip().lower())


_MAX_NAME_LEN = 200


async def _excluded_normalized(db: Any, chemical_id: int) -> set[str]:
    """该化合物主表两列的 normalized(摄入时排除)。"""
    row = (await db.execute(text("""
        SELECT preferred_name, iupac_name FROM chemistry.chemicals WHERE id=:id
    """), {"id": chemical_id})).first()
    if not row:
        return set()
    return {normalize_name(v) for v in (row[0], row[1]) if v}


async def ingest_chemical_names(
    db: Any,
    chemical_id: int,
    *,
    source: str,
    items: list[tuple[str, str, str]],  # (kind, lang, raw_name)
) -> int:
    """全量替换该 (chemical_id, source) 的 name_index 行, 返回插入行数。

    事务由调用方管理(与 upsert_externals / sync_chemical_core 同事务)。
    items 为空时等价于清空该 source 的行(镜像源被清空时同步清空)。
    """
    excluded = await _excluded_normalized(db, chemical_id)
    await db.execute(text("""
        DELETE FROM chemistry.name_index WHERE chemical_id=:id AND source=:source
    """), {"id": chemical_id, "source": source})
    if not items:
        return 0
    # 按 (kind, lang, normalized) 去重, 保序; 值保留首次出现的原始名
    dedup: dict[tuple[str, str, str], str] = {}
    for kind, lang, raw in items:
        n = normalize_name(raw)
        if not n or len(n) > _MAX_NAME_LEN:
            continue
        dedup.setdefault((kind, lang, n), raw)
    rows = [
        (kind, lang, n) for (kind, lang, n) in dedup
        if n not in excluded
    ]
    if not rows:
        return 0
    await db.execute(text("""
        INSERT INTO chemistry.name_index (chemical_id, name, lang, normalized, source, kind)
        SELECT :id, t.name, t.lang, t.normalized, :source, t.kind FROM unnest(
            CAST(:kinds AS text[]), CAST(:langs AS text[]),
            CAST(:norms AS text[]), CAST(:raws AS text[]))
        AS t(kind, lang, normalized, name)
        ON CONFLICT (chemical_id, source, kind, normalized) DO NOTHING
    """), {
        "id": chemical_id,
        "source": source,
        "kinds": [r[0] for r in rows],
        "langs": [r[1] for r in rows],
        "norms": [r[2] for r in rows],
        "raws": [dedup[(r[0], r[1], r[2])] for r in rows],
    })
    return len(rows)


async def ingest_from_entry_cn(
    db: Any, chemical_id: int, entry: dict[str, Any] | None,
    supplier_names: list[str | None],
) -> None:
    """CB 挂点: chemical_cb 落库同事务调用。

    中文名称(name_cn) + 中文别名(alias_cn) + 英文别名(alias_en) + 供应商(supplier)。
    entry 为 None(not_found)时清空该 source。
    """
    items: list[tuple[str, str, str]] = []
    if entry:
        for row in entry.get("basic", []):
            if len(row) == 2 and row[0] == "中文名称" and row[1]:
                items.append(("name_cn", "cn", row[1]))
        aliases = entry.get("aliases") or {}
        for v in aliases.get("cn", []) or []:
            items.append(("alias_cn", "cn", v))
        for v in aliases.get("en", []) or []:
            items.append(("alias_en", "en", v))
    for v in supplier_names:
        if v:
            items.append(("supplier", "cn", v))
    await ingest_chemical_names(db, chemical_id, source="cb", items=items)


async def ingest_from_synonyms(
    db: Any, chemical_id: int, synonyms: list[str] | None,
) -> None:
    """PubChem 挂点: sync_chemical_core 内 synonyms 有效时调用。

    synonyms 为 None 表示本次不涉及(保持镜像); 非 None 空/非空列表全量替换。
    """
    if synonyms is None:
        return
    items = [("synonym_en", "en", v) for v in synonyms]
    await ingest_chemical_names(db, chemical_id, source="pubchem", items=items)
