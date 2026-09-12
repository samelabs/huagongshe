"""统一搜索查询构造服务层 — 自 api/routes.py 下沉, 逻辑零改动(批次5a)。

外部引用者: routes.search。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import text

from ..chemistry import CAS_RE, DTXSID_RE, INCHIKEY_RE
from .chemicals import (
    CHEMICAL_SELECT, IDENTIFIER_ARRAYS, MIN_FUZZY_NAME_LENGTH,
    bounded_substructure_smiles, fetch_chemicals, name_query_width,
    reaction_lookup,
)
from .name_index import normalize_name


def cjk_char_count(value: str) -> int:
    """CJK 字符计数(Han/Hiragana-Katakana/Hangul), 与 name_query_width 同字符域。"""
    return sum(
        1 for ch in value
        if "\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff"
        or "\uac00" <= ch <= "\ud7af"
    )


def is_two_cjk_query(nq: str) -> bool:
    """normalized query 恰好由两个 CJK 字符组成(如 甲醇)。混合查询(甲醇A/甲醇-d4)为 False。"""
    return len(nq) == 2 and cjk_char_count(nq) == 2


def allows_substring_fallback(nq: str) -> bool:
    """是否允许 tier3 substring fallback: 复用既有最短名称契约(width), 且非纯两字 CJK。"""
    return (
        name_query_width(nq) >= MIN_FUZZY_NAME_LENGTH
        and not is_two_cjk_query(nq)
    )


async def run_search_query(
    db: Any, query: str, mode: str, canonical: Any, page: int, page_size: int,
    offset: int,
    *, actor_id: int | None = None, threshold: float = 0.7,
) -> tuple[list[dict[str, Any]], int | None, list[dict[str, Any]], bool, Any]:
    """执行搜索主体(化合物命中/total/反应/cas_fetch_pending/canonical 回写)。

    返回 (chemicals, total, reactions, cas_fetch_pending, canonical)。
    canonical 可能被 substructure 分支重新赋值(bounded), 调用方需取回。
    actor_id: 鉴权用户 id(匿名=None) — 仅用于 CAS-miss 入队限流身份。
    threshold: similarity 模式阈值(0.4-1.0, 默认 0.7), 与 /chemicals/{id}/similarity 同语义。
    """
    chemicals: list[dict[str, Any]] = []
    total: int | None = None
    cas_fetch_pending = False
    cas_fetch_hit_id: int | None = None  # 0902 P3b: 同步拉命中, 前端直跳详情页
    clauses: list[str] = []
    params: dict[str, Any] = {}
    try:
        if mode == "exact":
            await db.execute(text("SET LOCAL statement_timeout = '5s'"))
        if mode == "substructure":
            if not canonical:
                raise HTTPException(400, "无法识别该 SMILES 结构")
            canonical = bounded_substructure_smiles(canonical)
            # P0(0912): 有上限 GiST snapshot + Redis(同 chemicals.substructure_page) —
            # 无序 GiST 必被 planner 选中, 深页不再重扫候选集, TTL 内分页确定。
            from .chemicals import (SUBSTRUCTURE_SNAPSHOT_CAP, hydrate_chemicals,
                                    substructure_snapshot)
            from .chemicals import _snapshot_total
            ids = await substructure_snapshot(db, canonical)
            total = _snapshot_total(ids, offset, page_size)
            chemicals = await hydrate_chemicals(db, ids[offset:offset + page_size])
        elif mode == "similarity":
            if not canonical:
                raise HTTPException(400, "无法识别该 SMILES 结构")
            await db.execute(text("SET LOCAL statement_timeout = '8s'"))
            # KNN GiST 保持; threshold 后过滤 + Python 侧分页(同 similarity_page)。
            window = offset + page_size
            chemicals = await fetch_chemicals(db, f"""
                SELECT {CHEMICAL_SELECT},
                       1 - (c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles)))
                FROM chemistry.chemicals c
                WHERE c.mol IS NOT NULL
                ORDER BY c.morgan_bfp <%> morganbv_fp(mol_from_smiles(:smiles))
                LIMIT :window
            """, {"smiles": canonical, "window": window})
            qualifying = [item for item in chemicals if (item.get("similarity") or 0) >= threshold]
            qualifying.sort(key=lambda item: item.get("similarity") or 0, reverse=True)
            # total 语义(0912): prefix 内已跌破 threshold/prefix 未满 ⇒ 精确总数;
            # 否则 None("更多结果")。禁止用本页条数冒充总数。
            cut_inside = len(chemicals) < window or bool(
                chemicals and (chemicals[-1].get("similarity") or 0) < threshold)
            total = offset + len(qualifying) if cut_inside else None
            chemicals = qualifying[offset:offset + page_size]
        else:
            clauses = []
            params = {"q": query, "uq": query.upper(), "limit": page_size, "offset": offset}
            name_index_hit = False
            prefix, sep, raw_value = query.partition(":")
            if sep and prefix.lower() in IDENTIFIER_ARRAYS:
                clauses.append(f"c.{IDENTIFIER_ARRAYS[prefix.lower()]} @> ARRAY[:qv]")
                params["qv"] = raw_value.strip()
            elif sep and prefix.lower() == "cid" and raw_value.strip().isdigit():
                clauses.append("c.pubchem_cid = :number")
                params["number"] = int(raw_value)
            elif sep and prefix.lower() == "id" and raw_value.strip().isdigit():
                clauses.append("c.id = :number")
                params["number"] = int(raw_value)
            else:
                if query.isdigit():
                    clauses.extend(["c.id = :number", "c.pubchem_cid = :number"])
                    params["number"] = int(query)
                if CAS_RE.fullmatch(query):
                    clauses.append("c.cas_numbers @> ARRAY[:q]")
                elif INCHIKEY_RE.fullmatch(query.upper()):
                    clauses.append("c.inchikey = :uq")
                elif DTXSID_RE.fullmatch(query):
                    clauses.append("c.dtxsid = :uq")
                elif query.upper().startswith("CHEMBL"):
                    clauses.append("c.chembl_ids @> ARRAY[:q]")
                elif query.upper().startswith("CHEBI:"):
                    clauses.append("c.chebi_ids @> ARRAY[:q]")
                elif canonical:
                    from rdkit import Chem as _Chem
                    _mol = _Chem.MolFromSmiles(canonical)
                    _ik = _Chem.MolToInchiKey(_mol) if _mol else None
                    clauses.append("(c.smiles = :smiles AND c.mol IS NOT NULL)")
                    params["smiles"] = canonical
                    if _ik:
                        clauses.append("c.inchikey = :ik")
                        params["ik"] = _ik
            if clauses:
                chemicals = await fetch_chemicals(db, f"""
                    SELECT {CHEMICAL_SELECT}
                    FROM chemistry.chemicals c
                    WHERE {' OR '.join(clauses)}
                    ORDER BY c.id LIMIT :limit OFFSET :offset
                """, params)
                # CAS miss -> standalone CB 任务(2026-08-27): 只入队不同步拉。
                # 三态: pending=在途 / miss=CB负缓存 / 新入队也返回 pending。
                # 鉴权用户按 actor.id 限流; 匿名(BFF/SSR=loopback)共享全局桶
                # 30/min(BFF 后无真实IP可用, 靠 dedupe+深度闸门兜底)。
                # 限流/入队失败一律降级为不入队, 绝不阻塞搜索响应。
                if (
                    not chemicals and page == 1 and CAS_RE.fullmatch(query)
                ):
                    # 0904 敞口收口: 分支注释宣称限流但无 enforce 调用(匿名可
                    # 无限建占位行+触发外部链)。按注释原口径补齐: 鉴权用户
                    # 10/min/actor; 匿名(BFF/SSR=loopback, 无真实IP)共享全局桶
                    # 30/min。超限/限速服务异常一律降级为不入队(state=miss),
                    # 绝不阻塞搜索响应(注释原语义); 只挡占行+入队副作用面。
                    rate_state = "ok"
                    try:
                        from ..core.rate_limit import enforce
                        if actor_id is not None:
                            await enforce("cas-search-fetch", str(actor_id), 10, 60)
                        else:
                            await enforce("cas-search-fetch", "anonymous-global", 30, 60)
                    except Exception:
                        rate_state = "miss"
                    try:
                        from .cb import (
                            cas_search_state, enqueue_cas_search_fetch,
                            sync_fetch_and_store,
                        )
                        # rate 拒绝时跳过 state 询问, state 保持 "miss" 之外的
                        # 平价值: 只是不入队, 不对 CB 收录下任何结论(与
                        # cas_search_state 的 miss=终态负缓存语义区分)。
                        state = "throttled" if rate_state == "miss" else await cas_search_state(db, query)
                        if state == "new":
                            # 0902 P3b: 同步拉首屏 — 占行后当场抓 CB(3s 预算,
                            # 路径B实测 ~1.5s), 命中即本次响应带回 chemical_id,
                            # 前端直接跳详情页, 零轮询。失败/超时降级入列(80 分)。
                            # 治理不变: 治理交互不治理总量, dedupe 活跃窗防重复。
                            # 0907 门禁收口: resolver 裁定结果直接穿透 —
                            # chemical_id 非空(EXACT/EQUIVALENT/NEW 占位行)才
                            # 同步拉; None(AMBIGUOUS/CONFLICT)不落到任何候选行,
                            # 旧 cas_numbers LIMIT 1 任意选行旁路已删除。
                            enqueued, _res_status, row_id = await enqueue_cas_search_fetch(
                                db, cas_number=query,
                            )
                            await db.commit()
                            if enqueued:
                                synced = None
                                if row_id is not None:
                                    synced = await sync_fetch_and_store(
                                        db, chemical_id=int(row_id), cas_number=query,
                                    )
                                if row_id is not None and synced and synced.get("status") == "ok":
                                    cas_fetch_hit_id = int(row_id)
                                    state = "hit"
                                else:
                                    state = "pending"
                            else:
                                state = "miss"
                    except Exception:
                        await db.rollback()  # 入队失败不阻塞搜索响应
                        state = "new"
                    if state == "pending":
                        cas_fetch_pending = True
            # SMILES miss -> 建行入库(2026-08-29): canonical 校验通过但库内无行时,
            # 复用反应侧 resolve_or_create_chemical 同套逻辑(本地 RDKit 算结构三件),
            # 本次响应即返回该行. 结构行与反应创建同形态, 不新增入队/限流(结构合法
            # 即行合法, 延伸字段留 PB/CB 自然演进). 建行失败降级为空结果, 不阻塞.
            if not chemicals and page == 1 and canonical and len(query) <= 4000:
                try:
                    from .reactions import resolve_or_create_chemical
                    chemical_id, _created = await resolve_or_create_chemical(db, canonical)
                    created = await fetch_chemicals(db, f"""
                        SELECT {CHEMICAL_SELECT}
                        FROM chemistry.chemicals c WHERE c.id = :id
                    """, {"id": chemical_id})
                    if created:
                        await db.commit()
                        chemicals = created
                    else:
                        await db.rollback()
                except Exception:
                    await db.rollback()  # 建行失败不阻塞搜索响应
            if not chemicals and not canonical and name_query_width(query) >= MIN_FUZZY_NAME_LENGTH:
                # Keep the two trigram indexes independent. A cross-column OR on
                # 124M rows is both slower and less predictable than two bounded scans.
                # CJK 短语跳过前两段: preferred_name/iupac 全英文, 2 字中文的 trigram
                # 索引选择性崩塌(乙醇 bitmap 吐 42 万候选 91s); 中文名只活在这段。
                has_cjk = name_query_width(query) > len(query)
                if not has_cjk:
                    chemicals = await fetch_chemicals(db, f"""
                        SELECT {CHEMICAL_SELECT}
                        FROM chemistry.chemicals c
                        WHERE c.preferred_name ILIKE '%' || :q || '%'
                        ORDER BY c.id LIMIT :limit OFFSET :offset
                    """, {"q": query, "limit": page_size, "offset": offset})
                    if len(chemicals) < page_size:
                        secondary = await fetch_chemicals(db, f"""
                            SELECT {CHEMICAL_SELECT}
                            FROM chemistry.chemicals c
                            WHERE c.iupac_name ILIKE '%' || :q || '%'
                            ORDER BY c.id LIMIT :limit OFFSET :offset
                        """, {"q": query, "limit": page_size, "offset": offset})
                        seen = {item["id"] for item in chemicals}
                        # 相关性排序: preferred_name 命中段排在前, iupac 段追加在后.
                        # 不再按 id 归并排序(id 排序会让低段位命中挤掉精确名匹配).
                        chemicals.extend(item for item in secondary if item["id"] not in seen)
                        chemicals = chemicals[:page_size]
                # 第三段: name_index(中文名/别名/供应商名/synonyms 的派生镜像)。
                # 只在前两段不足一页时下探, 前两路零改动。
                if (has_cjk or len(chemicals) < page_size) and offset == 0:
                    # tier3 重排(2026-09-13): 先 exact normalized 等值命中, substring
                    # 只作为 fallback —— exact 永远先于 substring, 与 canonical name
                    # 定义无关。
                    nq = normalize_name(query)
                    # 仅「整个 query 恰好由两个 CJK 字符组成」禁止 substring;
                    # 混合查询(甲醇A/A甲醇/甲醇-d4)不受此限, 保留原 fallback。
                    tertiary_ids = (await db.execute(text("""
                        SELECT DISTINCT chemical_id FROM chemistry.name_index
                        WHERE normalized = :nq
                        ORDER BY chemical_id LIMIT :limit
                    """), {"nq": nq, "limit": page_size})).scalars().all()
                    if not tertiary_ids and allows_substring_fallback(nq):
                        # 两字 CJK 禁止 substring fallback: 2 字 trigram 选择性崩塌,
                        # planner 为 ORDER BY+LIMIT 弃 GIN 走 chemical_id 索引全扫
                        # (甲醇实测滤 173 万行 ~700ms, 并发下逼 5s statement_timeout);
                        # exact equality 走 GIN 索引 40ms。≥3 字保留 substring 下探。
                        tertiary_ids = (await db.execute(text("""
                            SELECT DISTINCT chemical_id FROM chemistry.name_index
                            WHERE normalized LIKE '%' || :nq || '%'
                            ORDER BY chemical_id LIMIT :limit
                        """), {"nq": nq, "limit": page_size})).scalars().all()
                    if tertiary_ids:
                        name_index_hit = True
                        # 合并而非替换: 前两段结果保留, 去重后追加(与第二段同型).
                        # 相关性排序: 段位顺序 = preferred_name > iupac > name_index;
                        # 同义词层(如"Aspirin Impurity C")不得越过精确名命中.
                        seen = {item["id"] for item in chemicals}
                        fresh_ids = [i for i in tertiary_ids if i not in seen]
                        if fresh_ids:
                            more = await fetch_chemicals(db, f"""
                                SELECT {CHEMICAL_SELECT}
                                FROM chemistry.chemicals c
                                WHERE c.id = ANY(:ids)
                                ORDER BY c.id
                            """, {"ids": fresh_ids})
                            chemicals.extend(more)
                            chemicals = chemicals[:page_size]
            elif not chemicals and not canonical and name_query_width(query) < MIN_FUZZY_NAME_LENGTH:
                raise HTTPException(422, "名称查询至少需要 3 个字符（中文至少 2 个字）")
            # 搜索命中卡片 → 同时查 zh 记录态和时间(准线§1 统一触发, 2026-08-30):
            # 命中行六态判定, enqueue 态真实入列(超窗刷新/超窗重问/error)。
            # 首问/负缓存内不动作。命中多行只判第一页首行(卡片=代表行)。
            if (
                chemicals and page == 1 and CAS_RE.fullmatch(query)
            ):
                try:
                    from .cb import cb_decide, enqueue_cas_job
                    hit_id = chemicals[0]["id"]
                    decision = await cb_decide(db, hit_id)
                    if decision.startswith("enqueue") and decision != "enqueue_first":
                        await enqueue_cas_job(
                            db, chemical_id=hit_id, cas_number=query,
                            priority=40, request_context={"reason": "search_stale"},
                        )
                        await db.commit()
                except Exception:
                    await db.rollback()  # 判定/入列失败不阻塞搜索响应

        try:
            if mode == "exact" and not canonical and name_query_width(query) >= MIN_FUZZY_NAME_LENGTH:
                if name_index_hit:
                    pass  # 第三段贡献结果: 两列 count 不覆盖 name_index, 保持 None(更多结果)
                elif clauses:
                    total = (await db.execute(text(f"""
                        SELECT count(*) FROM chemistry.chemicals c
                        WHERE {' OR '.join(clauses)}
                    """), params)).scalar()
                else:
                    await db.execute(text("SET LOCAL statement_timeout = '3s'"))
                    total = (await db.execute(text("""
                        SELECT count(*) FROM chemistry.chemicals c
                        WHERE c.preferred_name ILIKE '%' || :q || '%'
                           OR c.iupac_name ILIKE '%' || :q || '%'
                    """), {"q": query})).scalar()
        except Exception:
            total = None

        reactions = await reaction_lookup(db, query, page_size) if mode == "exact" and page == 1 else []
        # 0902 P2: 身份键唯一命中直达 — 无歧义身份键(CAS/InChIKey/canonical SMILES/
        # 显式 id:/cid: 前缀)且恰 1 行化合物 0 反应 → 前端/API 跳详情页。
        # 纯数字无前缀不直达: hcid/cid/hrid 三路天然歧义(格式不可控, 用户裁定)。
        if (
            mode == "exact" and page == 1
            and len(chemicals) == 1 and not reactions
        ):
            _pfx, _s, _val = query.partition(":")
            _pfx = _pfx.strip().lower()
            unambiguous = bool(
                CAS_RE.fullmatch(query)
                or INCHIKEY_RE.fullmatch(query.upper())
                or canonical
                or (_s and _pfx in ("id", "cid") and _val.strip().isdigit())
            )
            if unambiguous:
                cas_fetch_hit_id = chemicals[0]["id"]
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(503, "查询超时，请使用更精确的名称、标识符或结构") from exc
    return chemicals, total, reactions, cas_fetch_pending, canonical, cas_fetch_hit_id
