"""name_index 摄入: 唯一写入方, 全量替换语义。

name_index 是纯派生镜像:
- source='cb'      镜像 chemical_cb.entry 全部 locale 的名称/别名
                  (I-087: ja/ko/de/en 与 zh-CN 平等) + 供应商档案名
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


async def ingest_from_cb_locales(db: Any, chemical_id: int) -> int:
    """CB 挂点: chemical_cb 落库同事务调用(0905 canonical schema)。

    I-087: 名称镜像取该化合物**全部 locale**、last_status='ok' 的
    chemical_cb 行的并集(I-055 的"并集+固定排序"语义推广到所有 locale;
    本事务刚 UPSERT 的行同事务可见, 已在并集内), 按 cb_number、locale
    固定排序 + (kind,lang,normalized) 首现去重 —— 结果与各行的刷新先后
    无关。每个 locale 收 identity.cn(当地名)与当地语言别名(alias_cn);
    identity.en 与英文别名(alias_en)各 locale 重复, 按 (kind,lang,
    normalized) 去重与 PK 冲突自然合并。

    lang 列取值: zh-CN 沿用历史 'cn'(attach_localized_names 依赖
    (name_cn,'cn','cb') 三元组解析中文主标题, 17 万存量行同为 'cn',
    统一改码需要额外数据迁移且引入部署/回填顺序窗口), 其余 locale
    原样(ja/ko/de/en)。

    supplier 名不再由调用方按当次载荷传入(否则非 zh 行刷新会把它清掉),
    改为镜像 chemical_supplier_listing ⋈ profile 的当前行 —— 与刷新
    顺序无关。ok 行全部消失(全 error/删除)时名称清空, supplier 随
    listing 镜像保留, 镜像语义不变。
    """
    items: list[tuple[str, str, str]] = []
    # R4: 每个 cb_number 内 zh-CN 永远第一个处理。name_index 的 PK 不含
    # lang, 其他语言当地名归一化后与中文名相同时先到先得 —— de/en/ja/ko
    # 按字母序都在 zh-CN 前面, 会抢走 (name_cn, 'cn') 行, attach_localized_
    # names 就解析不出中文主标题(生产抽样约 1/5600 受影响)。zh-CN 优先后
    # 冲突时 'cn' 行必胜, 其余 locale 内部仍按字母序, 结果保持确定。
    entries = (await db.execute(text("""
        SELECT locale, entry FROM chemistry.chemical_cb
        WHERE chemical_id=:id AND last_status='ok'
        ORDER BY cb_number ASC NULLS LAST, (locale = 'zh-CN') DESC, locale ASC
    """), {"id": chemical_id})).all()
    for locale, row_entry in entries:
        if not row_entry:
            continue
        lang = "cn" if locale == "zh-CN" else str(locale)
        identity = row_entry.get("identity") or {}
        cn = identity.get("cn")
        if isinstance(cn, str) and cn:
            items.append(("name_cn", lang, cn))
        # 数据防御: 别名字段异常形态(null/标量)按缺失处理, 不逐字符迭代
        for kind, key in (("alias_cn", "alias_cn"), ("alias_en", "alias_en")):
            values = identity.get(key)
            if isinstance(values, list):
                alias_lang = "en" if key == "alias_en" else lang
                items.extend(
                    (kind, alias_lang, v) for v in values if isinstance(v, str) and v
                )
    supplier_names = (await db.execute(text("""
        SELECT p.name FROM chemistry.chemical_supplier_listing l
        JOIN chemistry.chemical_supplier_profile p ON p.cbsid=l.cbsid
        WHERE l.chemical_id=:id AND p.name IS NOT NULL
        ORDER BY l.cbsid ASC
    """), {"id": chemical_id})).scalars().all()
    for v in supplier_names:
        items.append(("supplier", "cn", v))
    return await ingest_chemical_names(db, chemical_id, source="cb", items=items)


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
