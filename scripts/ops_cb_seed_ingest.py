"""ChemicalBook sqlite ingestion: seed loader + seed scheduler (0907).

两阶段架构(立项冻结):
  Phase A seed loader    — sqlite → ingestion.chemicalbook_seed 账本。
                           绝不接触 chemistry.chemicals / cas_jobs。
  Phase B seed scheduler — 从 ledger 取 seed, 实时正式 resolver, 按需
                           materialize NEW placeholder, 受 backlog 高水位
                           约束 enqueue cas_jobs。

治理铁律:
  importer 不拥有 identity decision 权。所有归属来自
  api.services.identity.resolve_chemical / canonicalize_id。
  ledger 的 last_chemical_id 只是运行记录, scheduler 每次重新 resolve,
  使用前 canonicalize。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sqlite3
import sys
import time
from typing import Any

sys.path.insert(0, "/var/www/huagongshe")  # api 包所在(仓库根)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

log = logging.getLogger("hgs.ingest.cb_seed")

CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")

SEED_STATUSES = ("ACCEPTED", "RESOLVED_EXISTING", "PENDING_NEW",
                 "AMBIGUOUS", "CONFLICT", "ENQUEUED", "ERROR")


def db_url() -> str:
    raw = os.environ["HGS_DATABASE_URL"]
    # postgresql://user:pass@host/db?... → asyncpg dialect
    m = re.match(r"postgres(?:ql)?://([^:]+):([^@]+)@([^/]+)/(\w+)", raw)
    if m:
        return (f"postgresql+asyncpg://{m.group(1)}:{m.group(2)}"
                f"@{m.group(3)}/{m.group(4)}")
    m2 = re.match(r"postgres(?:ql)?\+asyncpg://", raw)
    if m2:
        return raw
    raise ValueError("unrecognized HGS_DATABASE_URL scheme")


# ---------------------------------------------------------------- Phase A

async def cmd_load(args: argparse.Namespace) -> None:
    """sqlite → ledger, keyset by cb_number, 幂等 UPSERT, 零 identity 副作用。"""
    # 0907 fail-closed (与 scheduler 同规): 无显式 scope 禁止装载
    if not (getattr(args, "cohort_file", "") or getattr(args, "cb_list", "")
            or getattr(args, "all", False)):
        print(json.dumps({"error": "refusing: no explicit scope "
              "(--cohort-file | --cb-list | --all required)"}))
        raise SystemExit(2)
    eng = create_async_engine(db_url(), pool_size=4)
    src = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    cur: str = args.start_after or ""
    cohort_cbs = None
    n_read = n_new = n_unchanged = n_skip = 0
    t0 = time.time()
    while True:
        rows = src.execute(
            "SELECT cb_number, cas FROM compounds"
            " WHERE cb_number > ? ORDER BY cb_number LIMIT ?",
            (cur, args.batch)).fetchall()
        if not rows:
            break
        if cohort_cbs is None and (getattr(args, "cohort_file", "")
                                   or getattr(args, "cb_list", "")):
            if getattr(args, "cb_list", ""):
                cohort_cbs = set(json.load(open(args.cb_list)))
                log.info("cb-list file: %s cbs=%s", args.cb_list, len(cohort_cbs))
            else:
                _d = json.load(open(args.cohort_file))
                cohort_cbs = set()
                for v in _d["detail"].values():
                    cohort_cbs.update(x["cb"] for x in v)
            log.info("cohort file: %s unique cbs=%s",
                     args.cohort_file, len(cohort_cbs))
        payload = []
        for cb, cas in rows:
            cur = cb
            if cohort_cbs is not None and cb not in cohort_cbs:
                continue
            s = (cas or "").strip()
            if not CAS_RE.match(s):
                n_skip += 1          # 空/非法 CAS 不入账本(立项口径)
                continue
            payload.append({"cb": cb, "cas": s})
        if payload:
            if args.dry_run:
                n_new += len(payload)
            else:
                async with eng.begin() as db:
                    # 幂等: 冲突时只刷新 cas 语义不变字段; status 等治理字段
                    # 绝不被 loader 重置(重跑不回退已调度状态)。
                    before = (await db.execute(text(
                        "SELECT count(*) FROM ingestion.chemicalbook_seed"
                        " WHERE cb_number = ANY(:cbs)"),
                        {"cbs": [p_["cb"] for p_ in payload]})).scalar()
                    await db.execute(text("""
                        INSERT INTO ingestion.chemicalbook_seed (cb_number, cas)
                        VALUES (:cb, :cas)
                        ON CONFLICT (cb_number) DO UPDATE
                        SET cas = EXCLUDED.cas, updated_at = now()
                        WHERE chemicalbook_seed.cas IS DISTINCT FROM EXCLUDED.cas
                    """), payload)
                    after = (await db.execute(text(
                        "SELECT count(*) FROM ingestion.chemicalbook_seed"
                        " WHERE cb_number = ANY(:cbs)"),
                        {"cbs": [p_["cb"] for p_ in payload]})).scalar()
                    n_new += after - before
                    n_unchanged += len(payload) - (after - before)
        n_read += len(rows)
        if args.limit and n_new + n_unchanged >= args.limit:
            break
        if n_read % 50000 == 0:
            log.info("loader progress read=%s new=%s unchanged=%s skip=%s",
                     n_read, n_new, n_unchanged, n_skip)
    print(json.dumps({
        "cmd": "load", "dry_run": args.dry_run, "read": n_read,
        "new": n_new, "unchanged": n_unchanged, "skipped_invalid_or_empty": n_skip,
        "last_cb": cur, "elapsed_s": round(time.time() - t0, 1)}))
    await eng.dispose()


# ---------------------------------------------------------------- Phase B

async def _backlog(db: Any) -> int:
    return (await db.execute(text(
        "SELECT count(*) FROM maintenance.cas_jobs"
        " WHERE status IN ('queued','leased')"))).scalar()


async def _schedule_one(db: Any, counts: dict, args: argparse.Namespace,
                        cb: str, cas: str, prev_status: str,
                        enq_state: list) -> None:
    """单 seed 状态机; 调用方持有事务, 异常向上抛由调用方回滚记 ERROR。"""
    from api.services.identity import resolve_chemical
    from api.services.cb import enqueue_cas_job
    # 铁律: 每次 re-resolve, 绝不信 ledger 缓存; NEW 只在 scheduler
    # 选中时物化(create=True), AMBIGUOUS 绝不 create。
    res = await resolve_chemical(
        db, cas=cas,
        create=(prev_status in ("ACCEPTED", "PENDING_NEW")))  # 0906: 延迟物化铁律不变
    if res.status in ("EXACT", "EQUIVALENT"):
        await db.execute(text("""
            UPDATE ingestion.chemicalbook_seed
            SET status='RESOLVED_EXISTING', last_chemical_id=:cid,
                resolved_at=now(), updated_at=now(), attempts=attempts+1
            WHERE cb_number=:cb
        """), {"cid": res.chemical_id, "cb": cb})
        counts["RESOLVED_EXISTING"] += 1
    elif res.status == "NEW":
        # 实时确认仍 NEW → 物化占位行(resolver 内建, 入门键=cas)
        await db.execute(text("""
            UPDATE ingestion.chemicalbook_seed
            SET status='PENDING_NEW', last_chemical_id=:cid,
                resolved_at=now(), updated_at=now(), attempts=attempts+1
            WHERE cb_number=:cb
        """), {"cid": res.chemical_id, "cb": cb})
        counts["CREATED_PLACEHOLDER"] += 1
    elif res.status == "AMBIGUOUS":
        await db.execute(text("""
            UPDATE ingestion.chemicalbook_seed
            SET status='AMBIGUOUS', last_chemical_id=NULL,
                resolved_at=now(), updated_at=now(), attempts=attempts+1
            WHERE cb_number=:cb
        """), {"cb": cb})
        counts["AMBIGUOUS"] += 1
        return
    elif res.status == "CONFLICT":
        await db.execute(text("""
            UPDATE ingestion.chemicalbook_seed
            SET status='CONFLICT', last_chemical_id=NULL,
                last_error='resolver CONFLICT', resolved_at=now(),
                updated_at=now(), attempts=attempts+1
            WHERE cb_number=:cb
        """), {"cb": cb})
        counts["CONFLICT"] += 1
        return
    else:
        raise RuntimeError(f"unexpected resolver status {res.status}")
    # enqueue(受 max_enqueue 约束; active dedupe_key 在 enqueue_cas_job 内)
    if args.max_enqueue >= 0 and enq_state[0] < args.max_enqueue:
        ok = await enqueue_cas_job(
            db, chemical_id=int(res.chemical_id), cas_number=cas,
            priority=20 if res.status in ("EXACT", "EQUIVALENT") else 40,
            request_context={"reason": "cb_seed_scheduler", "cb_number": cb})
        if ok:
            enq_state[0] += 1
            counts["ENQUEUED"] += 1
            await db.execute(text(
                "UPDATE ingestion.chemicalbook_seed"
                " SET enqueued_at=now(), status='ENQUEUED'"
                " WHERE cb_number=:cb"), {"cb": cb})


async def cmd_schedule(args: argparse.Namespace) -> None:
    """从 ledger 取 seed → 实时 resolver → 状态机 (逐 seed 独立事务)。"""
    counts = {"RESOLVED_EXISTING": 0, "CREATED_PLACEHOLDER": 0,
              "AMBIGUOUS": 0, "CONFLICT": 0, "ERROR": 0, "ENQUEUED": 0}
    enq_state = [0]  # 可变闭包: 已 enqueue 数
    processed = 0
    t0 = time.time()
    eng = create_async_engine(db_url(), pool_size=2)
    stop_reason: str | None = None
    cb_list = None
    # 0906 fail-closed: 无显式 scope 禁止处理 ledger (生产污染事故修复)
    if not (getattr(args, "cb_list", "") or getattr(args, "cohort_file", "")
            or getattr(args, "all", False)):
        print(json.dumps({"error": "refusing: no explicit scope "
              "(--cb-list | --cohort-file | --all required)"}))
        raise SystemExit(2)
    if getattr(args, "cb_list", ""):
        cb_list = json.load(open(args.cb_list))
        log.info("cb-list file: %s cbs=%s", args.cb_list, len(cb_list))
    elif getattr(args, "cohort_file", ""):
        _d = json.load(open(args.cohort_file))
        cb_list = sorted({x["cb"] for v in _d["detail"].values() for x in v})
        log.info("cohort-file scope: %s cbs=%s", args.cohort_file, len(cb_list))
    while processed < args.limit and stop_reason is None:
        async with eng.connect() as conn:
            await conn.execute(text("SET statement_timeout='600s'"))
            await conn.commit()
            async with conn.begin() as tx:
                backlog = (await conn.execute(text(
                    "SELECT count(*) FROM maintenance.cas_jobs"
                    " WHERE status IN ('queued','leased')"))).scalar()
                if args.max_enqueue > 0 and enq_state[0] >= args.max_enqueue:
                    # 0906 硬上限: cap>0 时达 cap 停整次 invocation。
                    # cap=0 = 纯 resolve-only 模式(处理但绝不入队)。
                    stop_reason = f"max_enqueue reached ({enq_state[0]})"
                    break
                if backlog > args.high_water:
                    stop_reason = f"high water ({backlog})"
                    break
                row = (await conn.execute(text("""
                    SELECT cb_number, cas, status, last_chemical_id
                    FROM ingestion.chemicalbook_seed
                    WHERE status IN ('ACCEPTED','PENDING_NEW','AMBIGUOUS',
                                     'RESOLVED_EXISTING')
                      AND cb_number > :after
                      AND (:no_list OR cb_number = ANY(:cbs))
                    ORDER BY cb_number LIMIT 1
                """), {"after": args.start_after or "",
                       "no_list": cb_list is None,
                       "cbs": cb_list or ["-"]})).first()
                if row is None:
                    stop_reason = "no more eligible seeds"
                    break
                args.start_after = row[0]
                processed += 1
                cb, cas, prev_status, _prev_cid = row
                try:
                    await _schedule_one(conn, counts, args, cb, cas,
                                        prev_status, enq_state)
                except Exception as exc:  # noqa: BLE001 — 单 seed 不熔断批次
                    await tx.rollback()
                    counts["ERROR"] += 1
                    log.warning("seed %s error: %s", cb, exc)
                    async with eng.begin() as db2:
                        await db2.execute(text("""
                            UPDATE ingestion.chemicalbook_seed
                            SET status='ERROR', last_error=:e,
                                attempts=attempts+1, updated_at=now()
                            WHERE cb_number=:cb AND status IN ('ACCEPTED','PENDING_NEW','AMBIGUOUS')
                        """), {"e": str(exc)[:500], "cb": cb})
    if stop_reason:
        log.info("scheduler stop: %s", stop_reason)
    print(json.dumps({"cmd": "schedule", "counts": counts,
                      "enqueued": enq_state[0], "processed": processed,
                      "stop_reason": stop_reason,
                      "elapsed_s": round(time.time() - t0, 1)}))
    await eng.dispose()


async def cmd_status(args: argparse.Namespace) -> None:
    eng = create_async_engine(db_url())
    async with eng.connect() as db:
        by_status = (await db.execute(text(
            "SELECT status, count(*) FROM ingestion.chemicalbook_seed"
            " GROUP BY 1 ORDER BY 1"))).fetchall()
        backlog = await _backlog(db)
    print(json.dumps({"by_status": dict(by_status), "cas_jobs_backlog": backlog}))
    await eng.dispose()


def _A(**kwargs):  # 测试辅助: kwargs Namespace
    return argparse.Namespace(**kwargs)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("load")
    pl.add_argument("--sqlite", default="/home/ubuntu/chemicalbook.sqlite")
    pl.add_argument("--batch", type=int, default=2000)
    pl.add_argument("--limit", type=int, default=0)
    pl.add_argument("--start-after", default="")
    pl.add_argument("--dry-run", action="store_true")
    pl.add_argument("--cb-list", default="",
                    help="json 文件(cb 数组): 只装载这些 cb_number")
    pl.add_argument("--all", action="store_true",
                    help="显式全量 sqlite valid seeds (必须明确写出)")
    pl.add_argument("--cohort-file", default="",
                    help="frozen cohort json: 只 load 文件内 cb_number")
    ps = sub.add_parser("schedule")
    ps.add_argument("--limit", type=int, default=100)
    ps.add_argument("--max-enqueue", type=int, default=20)
    ps.add_argument("--high-water", type=int, default=200)
    ps.add_argument("--start-after", default="")
    ps.add_argument("--cb-list", default="",
                    help="json 文件(cb 数组): 只处理这些 cb_number")
    ps.add_argument("--cohort-file", default="",
                    help="frozen cohort json: 只处理文件内 cb_number")
    ps.add_argument("--all", action="store_true",
                    help="显式全 ledger (必须明确写出)")
    sub.add_parser("status")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run({"load": cmd_load, "schedule": cmd_schedule,
                 "status": cmd_status}[args.cmd](args))


if __name__ == "__main__":
    main()
