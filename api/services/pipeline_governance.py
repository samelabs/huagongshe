"""A2 数据治理指标 (0912) — 只读诊断, 不修数据。

设计纪律(与任务书对齐):
- 语义三层分离: source_record / canonical_entity / derived_index, 禁止混称
- expensive 指标一律走"样本估算(sample) + 缓存(300s) + 明确标 mode",
  绝不在请求路径全表扫 1.24 亿 chemicals
- unavailable ≠ 0: 查询失败 → available=false, 绝不冒充数字
- orphan=0 是真 0(样本模式下如实标 sample 口径)
- drill-down 一律 LIMIT 20-50

指标清单(每条: definition / why / cost / mode):
CB:
  cb_name_index_missing   identity.cn 有值但 name_index(name_cn,cn,cb) 缺失
                         [sample→EXISTS 反查, pkey 命中, 便宜]
  cb_canonical_cb_number_null  chemical_cb 有行但 canonical.cb_number 空
                         [sample join pkey, 便宜]
  cb_locale_gaps          有 zh-CN 行但 locale 数 <2 的 chemical
                         [sample 聚合, 中等, 缓存]
  supplier_listing_orphan  listing 指向不存在 chemical
                         [sample→pkey 反查, 便宜; 理论 0]
  seed_enqueued_no_job    seed ENQUEUED 但 cas_jobs 无活跃行
                         [全量 cas_jobs 活跃键 ~小, join 账本主键, 中等]
PB:
  pb_canonical_sync_gap   chemical_pubchem 有行但 canonical 关键字段未同步
                         (preferred_name/formula/inchikey 任一空且 source 有值)
                         [sample join pkey, 便宜]
  pb_cid_no_source_record canonical.pubchem_cid 有值但无 chemical_pubchem 行
                         [sample→pkey 反查, 便宜]
INDEX:
  name_index_orphan       name_index 指向不存在 chemical
                         [sample→pkey 反查, 便宜; 理论 0]
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("admin.governance")

# 缓存: 进程内 last-known-good + 单飞(与 A1 _PIPELINE_STATS_* 同模式)
_GOV_CACHE: dict = {}          # {"v": snapshot, "ts": monotonic}
_GOV_TTL = 300.0               # 治理指标 5 分钟新鲜度足够(只读诊断)
_GOV_LOCK = asyncio.Lock()

# P1 (0912) stale-while-revalidate: 与 admin._PIPELINE_STATS_* 同语义 —
# TTL 过期但已有 last-known-good → 立即返回旧 snapshot, 后台独立 session
# 补一次刷新(单飞锁共用); 只有冷启动同步等待首扫。
_GOV_BG: set[asyncio.Task] = set()


async def _gov_refresh_bg() -> None:
    """后台刷新 governance snapshot: 独立 DB session, 请求 session 不入 task。"""
    async with _GOV_LOCK:
        c2 = _GOV_CACHE.get("v")
        if c2 is not None and _time.monotonic() - c2["ts"] <= _GOV_TTL:
            return
        from ..core.database import async_session
        async with async_session() as db:
            try:
                _GOV_CACHE["v"] = {"v": await governance_snapshot(db),
                                   "ts": _time.monotonic()}
            except Exception:  # noqa: BLE001 — last-known-good 语义
                logger.exception("governance background refresh failed (keep last-known-good)")


def _gov_spawn_refresh() -> None:
    """真正的 single-flight 门(同 admin._pipeline_stats_spawn_refresh):
    集合非空即已有后台刷新在跑 → 不再建任务; done_callback 消费异常。"""
    if _GOV_BG:
        return
    task = asyncio.get_running_loop().create_task(_gov_refresh_bg())
    _GOV_BG.add(task)

    def _reap(t: asyncio.Task) -> None:
        _GOV_BG.discard(t)
        if not t.cancelled():
            _ = t.exception()

    task.add_done_callback(_reap)

SAMPLE_ROWS = 3000             # 样本行数(所有 sample 指标统一)
DRILL_LIMIT = 50               # drill-down 上限(任务书 20-50)


def _wrap(ok: bool, value: Any = None, error: str | None = None,
          mode: str = "exact") -> dict:
    """统一包装: available / value / error / mode(exact|sample|estimate)。"""
    return {"available": ok, "value": value, "error": error, "mode": mode}


async def _q(db: AsyncSession, sql: str) -> list:
    return (await db.execute(text(sql))).fetchall()


async def _qone(db: AsyncSession, sql: str, params: dict | None = None):
    if params:
        return (await db.execute(text(sql), params)).scalar()
    return (await db.execute(text(sql))).scalar()


# ── CB 指标 ────────────────────────────────────────────────

def _sample_payload(sample_size: int, matched: int, **extra) -> dict:
    """统一抽样契约: exact=False, 只报样本事实, 禁换算全库总数。
    matched=样本中命中异常的行数; ratio=样本内比率(仅样本语义)。"""
    v = {"exact": False, "sample_size": int(sample_size),
         "matched": int(matched),
         "ratio": round(matched / sample_size, 4) if sample_size else None}
    v.update(extra)
    return v


async def cb_name_index_missing(db: AsyncSession) -> dict:
    """identity.cn 有值但 name_index 镜像缺失。
    sample 口径: zh-CN 行抽样 → EXISTS 反查 pkey。(全量精确=31,046 已离线实测,
    但服务端只报样本事实, 不把样本 matched 冒充全量 count。)"""
    rows = await _q(db, f"""
        WITH s AS (SELECT chemical_id, cb_number,
                          entry->'identity'->>'cn' AS cn
                   FROM chemistry.chemical_cb TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS})
                   WHERE locale='zh-CN' AND entry->'identity'->>'cn' IS NOT NULL)
        SELECT s.chemical_id, s.cb_number, s.cn,
               EXISTS (SELECT 1 FROM chemistry.name_index n
                       WHERE n.chemical_id=s.chemical_id
                         AND n.kind='name_cn' AND n.lang='cn' AND n.source='cb') AS has_ni
        FROM s
    """)
    missing = [r for r in rows if not r[3]]
    return _wrap(True, _sample_payload(len(rows), len(missing)), mode="sample")


async def cb_canonical_cb_number_null(db: AsyncSession) -> dict:
    rows = await _q(db, f"""
        WITH s AS (SELECT chemical_id FROM chemistry.chemical_cb
                   TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS}))
        SELECT s.chemical_id, c.cb_number
        FROM s JOIN chemistry.chemicals c ON c.id=s.chemical_id
    """)
    nulls = [r for r in rows if r[1] is None]
    return _wrap(True, _sample_payload(len(rows), len(nulls)), mode="sample")


async def cb_locale_gaps(db: AsyncSession) -> dict:
    """zh-CN 行存在但 locale 覆盖 <2(其他语言全缺)。sample 聚合。"""
    row = (await _q(db, f"""
        WITH s AS (SELECT DISTINCT chemical_id FROM chemistry.chemical_cb
                   TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS}) WHERE locale='zh-CN'),
        per AS (SELECT c.chemical_id, count(DISTINCT c.locale) n
                FROM chemistry.chemical_cb c JOIN s ON s.chemical_id=c.chemical_id
                GROUP BY c.chemical_id)
        SELECT count(*), count(*) FILTER (WHERE n < 2) FROM per
    """))[0]
    total, gaps = int(row[0]), int(row[1])
    return _wrap(True, _sample_payload(total, gaps), mode="sample")


async def supplier_listing_orphan(db: AsyncSession) -> dict:
    rows = await _q(db, f"""
        WITH s AS (SELECT chemical_id FROM chemistry.chemical_supplier_listing
                   TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS}))
        SELECT s.chemical_id FROM s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.chemicals c WHERE c.id=s.chemical_id)
    """)
    return _wrap(True, _sample_payload(SAMPLE_ROWS, len(rows)), mode="sample")


async def seed_enqueued_no_job(db: AsyncSession) -> dict:
    """seed ENQUEUED 但 cas_jobs 无活跃(queued/leased)对应行。
    cas_jobs 活跃集小(索引在), 账本按 cb_number 主键点查。"""
    row = await _qone(db, """
        SELECT count(*) FROM ingestion.chemicalbook_seed s
        WHERE s.status='ENQUEUED'
          AND NOT EXISTS (
            SELECT 1 FROM maintenance.cas_jobs j
            WHERE j.status IN ('queued','leased')
              AND j.dedupe_key LIKE 'cas:%:' || s.cas || ':%' || s.cb_number
          )
    """) if False else None
    # LIKE 拼接不可靠(dedupe_key 中段是 cas hash 而非明文 cas) → 该口径
    # 当前无法可靠计算: dedupe_key = cas:{chemical_id}:{cas_hash}:{cb_number},
    # cas_hash 无法从账本字段重建 → 标 deferred, 不造错误数字。
    return _wrap(False, error="dedupe_key 含不可重建的 cas hash, 无法从账本字段可靠对应; 需上游补显式关联键", mode="deferred")


# ── PB 指标 ────────────────────────────────────────────────

async def pb_canonical_sync_gap(db: AsyncSession) -> dict:
    """chemical_pubchem 有行但 canonical 同步字段空(preferred/formula/IK)。
    注意 source-record 有值才算"该同步而未同步"。"""
    rows = await _q(db, f"""
        WITH s AS (SELECT chemical_id, record_title
                   FROM chemistry.chemical_pubchem TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS}))
        SELECT s.chemical_id, s.record_title,
               c.preferred_name, c.molecular_formula, c.inchikey
        FROM s JOIN chemistry.chemicals c ON c.id=s.chemical_id
    """)
    gap = [r for r in rows
           if r[1] and (r[2] is None or r[3] is None or r[4] is None)]
    return _wrap(True, _sample_payload(len(rows), len(gap)), mode="sample")


async def pb_cid_no_source_record(db: AsyncSession) -> dict:
    rows = await _q(db, f"""
        WITH s AS (SELECT id FROM chemistry.chemicals TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS})
                   WHERE pubchem_cid IS NOT NULL)
        SELECT s.id FROM s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.chemical_pubchem p
                          WHERE p.chemical_id=s.id)
    """)
    return _wrap(True, _sample_payload(SAMPLE_ROWS, len(rows)), mode="sample")


# ── INDEX 指标 ─────────────────────────────────────────────

async def name_index_orphan(db: AsyncSession) -> dict:
    rows = await _q(db, f"""
        WITH s AS (SELECT chemical_id FROM chemistry.name_index
                   TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS}))
        SELECT s.chemical_id FROM s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.chemicals c WHERE c.id=s.chemical_id)
    """)
    return _wrap(True, _sample_payload(SAMPLE_ROWS, len(rows)), mode="sample")


async def name_index_distribution(db: AsyncSession) -> dict:
    """Search readiness: kind/lang/source 分布(全量聚合, name_index 850万,
    可走一次 GROUP BY, EXPLAIN 后缓存 5 分钟)。"""
    rows = await _q(db, """
        SELECT kind, lang, source, count(*) FROM chemistry.name_index
        GROUP BY kind, lang, source ORDER BY count(*) DESC LIMIT 30
    """)
    dist = [{"kind": r[0], "lang": r[1], "source": r[2], "count": int(r[3])}
            for r in rows]
    return _wrap(True, dist, mode="exact")


async def canonical_name_coverage(db: AsyncSession) -> dict:
    """canonical 命名覆盖率(estimated): pg_class 估行 + TABLESAMPLE 计比率。"""
    est = await _qone(db, "SELECT reltuples::bigint FROM pg_class WHERE oid='chemistry.chemicals'::regclass")
    row = (await _q(db, f"""
        SELECT count(*), count(preferred_name), count(iupac_name),
               count(molecular_formula), count(pubchem_cid)
        FROM (SELECT preferred_name, iupac_name, molecular_formula, pubchem_cid
              FROM chemistry.chemicals TABLESAMPLE SYSTEM_ROWS({SAMPLE_ROWS})) s
    """))[0]
    n = int(row[0])
    rate = lambda k: (int(row[k]) / n) if n else 0.0  # noqa: E731
    return _wrap(True, {
        "chemicals_estimated": int(est or 0),
        "sample_rows": n,
        "preferred_name_rate": round(rate(1), 4),
        "iupac_name_rate": round(rate(2), 4),
        "formula_rate": round(rate(3), 4),
        "pubchem_cid_rate": round(rate(4), 4),
    }, mode="sample")


# ── Identity governance (真实存在的持久化维度) ─────────────

async def identity_governance(db: AsyncSession) -> dict:
    """identity 治理分层(不互相顶替):
    - history: merge_log/redirect = 历史已执行 merge 记录
    - acquisition_pending: seed AMBIGUOUS = CB 采集/身份悬案(账本终态)
    - resolver_events: 逐次 AMBIGUOUS/CONFLICT 判定事件 —— 无持久化, 如实报
      "当前无可统计的 resolver 持久化事件", 禁用 seed/merge_log 顶替。"""
    seed = {r[0]: int(r[1]) for r in await _q(db, """
        SELECT status, count(*) FROM ingestion.chemicalbook_seed GROUP BY status
    """)}
    try:
        merged_24h = await _qone(db, "SELECT count(*) FROM maintenance.identity_merge_log WHERE merged_at >= now()-interval '24 hours'")
        merge_total = await _qone(db, "SELECT count(*) FROM maintenance.identity_merge_log")
        redirect_total = await _qone(db, "SELECT count(*) FROM maintenance.chemical_identity_redirect")
        history = {"merge_total": int(merge_total or 0),
                   "merged_last_24h": int(merged_24h or 0),
                   "redirect_total": int(redirect_total or 0)}
    except Exception as exc:  # noqa: BLE001 — merge/redirect 缺席时账本仍可示
        logger.warning("identity merge/redirect tables unreadable: %r", exc)
        history = None
    return _wrap(True, {
        "history": history,
        "acquisition_pending": {"ambiguous_seeds": seed.get("AMBIGUOUS", 0)},
        "source_miss": {"note": "见 /admin/pipeline cb.negative(来源未命中, 采集层口径)"},
        "resolver_events": None,
        "resolver_events_note": "当前无可统计的 resolver 持久化事件",
        "seed_ledger": seed,
    }, mode="exact")


# ── 汇总(带缓存+单飞+分区容错) ─────────────────────────────

_SECTIONS: dict[str, Any] = {
    "cb_name_index_missing": cb_name_index_missing,
    "cb_canonical_cb_number_null": cb_canonical_cb_number_null,
    "cb_locale_gaps": cb_locale_gaps,
    "supplier_listing_orphan": supplier_listing_orphan,
    "seed_enqueued_no_job": seed_enqueued_no_job,
    "pb_canonical_sync_gap": pb_canonical_sync_gap,
    "pb_cid_no_source_record": pb_cid_no_source_record,
    "name_index_orphan": name_index_orphan,
    "name_index_distribution": name_index_distribution,
    "canonical_name_coverage": canonical_name_coverage,
    "identity_governance": identity_governance,
}


async def governance_snapshot(db: AsyncSession) -> dict:
    """每个 section 独立 try/except: 单块失败 → available=false, 不拖垮整体。"""
    out: dict = {}
    for name, fn in _SECTIONS.items():
        try:
            out[name] = await fn(db)
        except Exception as exc:  # noqa: BLE001
            logger.exception("governance section %s failed", name)
            out[name] = _wrap(False, error=str(exc)[:200], mode="error")
    return out


async def get_governance(db: AsyncSession) -> dict:
    """last-known-good + stale-while-revalidate(冷启动同步等首个 single-flight,
    与 A1/P1 admin._PIPELINE_STATS_* 同语义)。"""
    cached = _GOV_CACHE.get("v")
    stale = False
    if cached is None or _time.monotonic() - cached["ts"] > _GOV_TTL:
        if cached is not None:
            # 已有 snapshot: 立即返回旧值标 stale, 锁空闲则后台补一次刷新
            stale = True
            if not _GOV_LOCK.locked():
                _gov_spawn_refresh()
        else:
            async with _GOV_LOCK:
                c2 = _GOV_CACHE.get("v")
                if c2 is not None and _time.monotonic() - c2["ts"] <= _GOV_TTL:
                    cached = c2
                else:
                    try:
                        snap = await governance_snapshot(db)
                        _GOV_CACHE["v"] = {"v": snap, "ts": _time.monotonic()}
                        cached = _GOV_CACHE["v"]
                    except Exception:
                        logger.exception("governance snapshot failed")
                        if _GOV_CACHE.get("v") is None:
                            raise
                        cached = _GOV_CACHE["v"]
                        stale = True
    return {
        "sections": cached["v"],
        "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "monotonic_ts": cached["ts"],
        "stale": stale,
        "ttl_seconds": int(_GOV_TTL),
    }


# ── Drill-down(带 LIMIT, 只支持有可靠持久化证据的) ─────────

_DRILLS: dict[str, str] = {
    "cb_name_index_missing": f"""
        SELECT s.chemical_id, s.cb_number, s.cn
        FROM (SELECT chemical_id, cb_number, entry->'identity'->>'cn' AS cn
              FROM chemistry.chemical_cb TABLESAMPLE SYSTEM_ROWS(20000)
              WHERE locale='zh-CN' AND entry->'identity'->>'cn' IS NOT NULL) s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.name_index n
                          WHERE n.chemical_id=s.chemical_id
                            AND n.kind='name_cn' AND n.lang='cn' AND n.source='cb')
        LIMIT {DRILL_LIMIT}
    """,
    "cb_canonical_cb_number_null": f"""
        SELECT s.chemical_id, s.cb_number, c.preferred_name
        FROM (SELECT chemical_id, max(cb_number) cb_number
              FROM chemistry.chemical_cb TABLESAMPLE SYSTEM_ROWS(20000)
              GROUP BY chemical_id) s
        JOIN chemistry.chemicals c ON c.id=s.chemical_id
        WHERE c.cb_number IS NULL
        LIMIT {DRILL_LIMIT}
    """,
    "pb_cid_no_source_record": f"""
        SELECT s.id, s.pubchem_cid, s.preferred_name
        FROM (SELECT id, pubchem_cid, preferred_name
              FROM chemistry.chemicals TABLESAMPLE SYSTEM_ROWS(20000)
              WHERE pubchem_cid IS NOT NULL) s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.chemical_pubchem p
                          WHERE p.chemical_id=s.id)
        LIMIT {DRILL_LIMIT}
    """,
    "supplier_listing_orphan": f"""
        SELECT s.chemical_id, s.cbsid
        FROM (SELECT chemical_id, cbsid FROM chemistry.chemical_supplier_listing
              TABLESAMPLE SYSTEM_ROWS(20000)) s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.chemicals c WHERE c.id=s.chemical_id)
        LIMIT {DRILL_LIMIT}
    """,
    "name_index_orphan": f"""
        SELECT s.chemical_id, s.kind, s.lang, s.source
        FROM (SELECT chemical_id, kind, lang, source FROM chemistry.name_index
              TABLESAMPLE SYSTEM_ROWS(20000)) s
        WHERE NOT EXISTS (SELECT 1 FROM chemistry.chemicals c WHERE c.id=s.chemical_id)
        LIMIT {DRILL_LIMIT}
    """,
    "identity_ambiguous_seeds": f"""
        SELECT cb_number, cas, status, updated_at
        FROM ingestion.chemicalbook_seed
        WHERE status='AMBIGUOUS' ORDER BY updated_at DESC
        LIMIT {DRILL_LIMIT}
    """,
    "identity_conflict_seeds": f"""
        SELECT cb_number, cas, status, last_error, updated_at
        FROM ingestion.chemicalbook_seed
        WHERE status='CONFLICT' ORDER BY updated_at DESC
        LIMIT {DRILL_LIMIT}
    """,
    "identity_merge_log": f"""
        SELECT m.merge_id, m.source_id, m.target_id, m.reason, m.merged_at
        FROM maintenance.identity_merge_log m ORDER BY m.merged_at DESC
        LIMIT {DRILL_LIMIT}
    """,
}


async def drill_down(db: AsyncSession, key: str) -> dict:
    if key not in _DRILLS:
        return {"available": False,
                "error": f"未知 drill-down: {key}",
                "rows": []}
    try:
        rows = await _q(db, _DRILLS[key])
        cols = list(rows[0]._mapping.keys()) if rows else []
        return {"available": True, "error": None,
                "columns": cols,
                "rows": [list(r) for r in rows],
                "limit": DRILL_LIMIT}
    except Exception as exc:  # noqa: BLE001
        logger.exception("drill-down %s failed", key)
        return {"available": False, "error": str(exc)[:200], "rows": []}


# 不支持 drill-down 的(明确列出, 不猜):
#   seed_enqueued_no_job — deferred(无可靠关联键)
#   pb_canonical_sync_gap — 可加, 但语义与 fixture 测试重叠, A2 不扩
DRILL_UNSUPPORTED = {
    "seed_enqueued_no_job": "deferred 指标(账本↔job 无可靠关联键), 无法 drill-down",
    "pb_canonical_sync_gap": "样本口径, drill-down 见 pb_cid_no_source_record",
    "cb_locale_gaps": "聚合口径, 样本行无单条异常语义",
    "name_index_distribution": "分布非异常, 无 drill-down 语义",
    "canonical_name_coverage": "覆盖率非异常清单",
    "identity_governance": "汇总; 逐条见 identity_*_seeds / identity_merge_log",
}
