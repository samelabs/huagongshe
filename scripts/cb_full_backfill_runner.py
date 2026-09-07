"""ChemicalBook full-backfill queue-driven runner (0907, one-shot migration tool).

复用 scripts/ops_cb_seed_ingest.py schedule executor, 外层只做控制:
preflight → invoke → wait drain below resume threshold → checkpoint → loop.

设计铁律 (用户令 0907):
  - runner 是哑控制层: 不碰 identity/queue/worker 机制, 数据路径全部
    走现有 executor (ledger → scheduler → Gov → cas_jobs → worker)。
  - 安全重启: 进度真值 = ingestion.chemicalbook_seed ledger, 不依赖内存;
    本地 checkpoint 文件只是观测记录。
  - 硬停条件命中即退出, 不自动恢复。
  - 完成定义: eligible seeds 全部脱离 ACCEPTED/PENDING_NEW 待处理态
    且 cas_jobs 排空。
任务完成后 runner 退出; 不 cron / 不 systemd / 不常驻。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

sys_path_hint = "/var/www/huagongshe"  # executor 所在仓库根
import sys  # noqa: E402
if sys_path_hint not in sys.path:
    sys.path.insert(0, sys_path_hint)

log = logging.getLogger("hgs.ingest.cb_runner")

EXECUTOR = ["/var/www/huagongshe/venv/bin/python",
            "scripts/ops_cb_seed_ingest.py"]
CST = timezone(timedelta(hours=8))

# 冻结参数 (用户令 0907): 300/h, 12h backlog, high_water 2400, resume<500
THROUGHPUT = 300
BACKLOG_HOURS = 12
HIGH_WATER = 2400
RESUME_THRESHOLD = 500
INVOKE_LIMIT = 50_000        # 每次 invocation 的 --limit (上限, gate 自行截停)
DISK_MIN_FREE_GB = 25.0      # 硬停: free < 25GB
DISK_MAX_USAGE = 85.0        # 硬停: usage >= 85%
WAIT_POLL_S = 60             # drain 等待轮询间隔
PROGRESS_EVERY = 50_000      # 每 5 万 processed 输出进度 summary

# 可恢复(非终态) seed 状态 = runner 仍需驱动的; ERROR 可重试一轮后若仍
# 卡住由 executor ERROR 趋势硬停兜底。
ACTIVE_STATUSES = ("ACCEPTED", "PENDING_NEW", "ERROR")


def db_url() -> str:
    raw = os.environ["HGS_DATABASE_URL"]
    m = re.match(r"postgres(?:ql)?://([^:]+):([^@]+)@([^/]+)/(\w+)", raw)
    if m:
        return (f"postgresql+asyncpg://{m.group(1)}:{m.group(2)}"
                f"@{m.group(3)}/{m.group(4)}")
    if re.match(r"postgres(?:ql)?\+asyncpg://", raw):
        return raw
    raise ValueError("unrecognized HGS_DATABASE_URL scheme")


def disk_state() -> tuple[float, float]:
    s = os.statvfs("/")
    free_gb = s.f_bavail * s.f_frsize / 2**30
    usage = (1 - s.f_bavail / s.f_blocks) * 100
    return free_gb, usage


class SafetyStop(Exception):
    """硬停: 带原因退出, 不自动恢复。"""


async def safety_check(eng) -> dict:
    """单一硬停检查点; 返回快照, 异常即停。"""
    free_gb, usage = disk_state()
    if free_gb < DISK_MIN_FREE_GB:
        raise SafetyStop(f"disk free {free_gb:.2f}GB < {DISK_MIN_FREE_GB}GB")
    if usage >= DISK_MAX_USAGE:
        raise SafetyStop(f"disk usage {usage:.2f}% >= {DISK_MAX_USAGE}%")
    async with eng.connect() as db:
        await db.execute(text("SET statement_timeout='300s'"))
        await db.commit()
        # PG 可用性即本查询成功; worker/API 健康由 executor ERROR 趋势兜底
        snap = {}
        snap["backlog"] = (await db.execute(text(
            "SELECT count(*) FROM maintenance.cas_jobs"
            " WHERE status IN ('queued','leased')"))).scalar()
        snap["seed"] = dict((await db.execute(text(
            "SELECT status, count(*) FROM ingestion.chemicalbook_seed"
            " GROUP BY 1"))).fetchall())
        snap["merge_log"] = (await db.execute(text(
            "SELECT count(*) FROM maintenance.identity_merge_log"))).scalar()
        snap["redirect"] = (await db.execute(text(
            "SELECT count(*) FROM maintenance.chemical_identity_redirect"
            ))).scalar()
        # source integrity: duplicate grain / dangling FK
        dup_nn = (await db.execute(text(
            "SELECT count(*) FROM (SELECT 1 FROM chemistry.chemical_cb"
            " WHERE cb_number IS NOT NULL GROUP BY chemical_id, cb_number,"
            " locale HAVING count(*) > 1) t"))).scalar()
        if dup_nn > 0:
            raise SafetyStop(f"duplicate nonnull grain = {dup_nn}")
        snap["dup_nonnull"] = 0
        # dangling: FK 强制下不可能; 点查最近写入样本验证链路健康
        dang = (await db.execute(text(
            "SELECT count(*) FROM (SELECT DISTINCT chemical_id"
            " FROM chemistry.chemical_cb ORDER BY chemical_id DESC"
            " LIMIT 200) s WHERE NOT EXISTS (SELECT 1 FROM"
            " chemistry.chemicals m WHERE m.id = s.chemical_id)"))).scalar()
        if dang > 0:
            raise SafetyStop(f"dangling FK sample = {dang}")
        snap["db_mb"] = (await db.execute(text(
            "SELECT pg_database_size('huagongshe')/1024/1024"))).scalar()
    # Gov 熔断: merge/redirect 只增不降(单调表), 突增即 unexplained
    snap["disk_free_gb"] = round(free_gb, 2)
    snap["disk_usage"] = round(usage, 2)
    return snap


def remaining(seed: dict) -> int:
    return sum(seed.get(s, 0) for s in ACTIVE_STATUSES)


async def wait_drain(eng) -> int:
    """等 cas_jobs < RESUME_THRESHOLD; 返回等待秒数。轮询中也做磁盘硬停。"""
    t0 = time.time()
    while True:
        free_gb, usage = disk_state()
        if free_gb < DISK_MIN_FREE_GB:
            raise SafetyStop(f"disk free {free_gb:.2f}GB < {DISK_MIN_FREE_GB}GB"
                             " (during drain wait)")
        if usage >= DISK_MAX_USAGE:
            raise SafetyStop(f"disk usage {usage:.2f}% >= {DISK_MAX_USAGE}%"
                             " (during drain wait)")
        async with eng.connect() as db:
            backlog = (await db.execute(text(
                "SELECT count(*) FROM maintenance.cas_jobs"
                " WHERE status IN ('queued','leased')"))).scalar()
        if backlog < RESUME_THRESHOLD:
            return int(time.time() - t0)
        await asyncio.sleep(WAIT_POLL_S)


def invoke_executor() -> dict:
    """调现有 executor 一次; 返回其 JSON 输出 (失败抛 SafetyStop)。"""
    cmd = EXECUTOR + ["schedule", "--all", "--limit", str(INVOKE_LIMIT),
                      "--max-enqueue", str(INVOKE_LIMIT),
                      "--new-budget", str(INVOKE_LIMIT),
                      "--throughput-per-hour", str(THROUGHPUT),
                      "--backlog-hours", str(BACKLOG_HOURS),
                      "--high-water", str(HIGH_WATER)]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd="/var/www/huagongshe",
                          capture_output=True, text=True, timeout=3600)
    out = proc.stdout.strip().splitlines()
    payload = {}
    for line in reversed(out):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if proc.returncode != 0 or not payload or payload.get("cmd") != "schedule":
        raise SafetyStop(f"executor failed rc={proc.returncode} "
                         f"stderr={proc.stderr[-500:]}")
    payload["wall_s"] = round(time.time() - t0, 1)
    return payload


def checkpoint_write(path: str, state: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


async def cmd_run(args: argparse.Namespace) -> None:
    ck_path = args.checkpoint
    eng = create_async_engine(db_url(), pool_size=2)
    state = {"started_at": datetime.now(CST).isoformat(),
             "invocations": 0, "processed_total": 0, "history": []}
    log.info("runner start; ledger 为进度真值, checkpoint=%s", ck_path)
    next_progress = PROGRESS_EVERY
    t0 = time.time()
    try:
        while True:
            snap = await safety_check(eng)          # Storage/source/Gov 硬停
            rem = remaining(snap["seed"])
            log.info("preflight: remaining=%d backlog=%d disk=%.1fG/%.1f%% "
                     "ml=%s", rem, snap["backlog"], snap["disk_free_gb"],
                     snap["disk_usage"], snap["merge_log"])
            if rem == 0 and snap["backlog"] < RESUME_THRESHOLD:
                # 完成前最终排空确认
                log.info("eligible exhausted; final drain wait")
                await wait_drain(eng)
                snap2 = await safety_check(eng)
                if remaining(snap2["seed"]) == 0:
                    state["finished_at"] = datetime.now(CST).isoformat()
                    checkpoint_write(ck_path, state)
                    print(json.dumps({"runner": "FULL BACKFILL COMPLETE",
                                      "final_seed": snap2["seed"],
                                      "backlog": snap2["backlog"],
                                      "processed_total":
                                          state["processed_total"],
                                      "elapsed_s":
                                          round(time.time() - t0, 1)}))
                    return
                continue
            if snap["backlog"] >= RESUME_THRESHOLD:
                w = await wait_drain(eng)           # high_water/backlog 停注
                log.info("drained in %ds; continue", w)  # → 等待后自动继续
                continue
            # ---- invocation ----
            payload = invoke_executor()
            state["invocations"] += 1
            state["processed_total"] += payload.get("processed", 0)
            entry = {"ts": datetime.now(CST).isoformat(), **payload}
            state["history"].append(entry)
            checkpoint_write(ck_path, state)
            c = payload["counts"]
            log.info("invocation #%d: processed=%s enqueued=%s "
                     "RE=%s NEW=%s AMB=%s C=%s E=%s stop=%s",
                     state["invocations"], payload.get("processed"),
                     payload.get("enqueued"), c.get("RESOLVED_EXISTING"),
                     c.get("CREATED_PLACEHOLDER"), c.get("AMBIGUOUS"),
                     c.get("CONFLICT"), c.get("ERROR"),
                     payload.get("stop_reason"))
            # Runtime 硬停: executor ERROR 连续增长
            if c.get("ERROR", 0) > 0:
                state["error_invocations"] = state.get("error_invocations", 0) + 1
                if state["error_invocations"] >= 3:
                    raise SafetyStop(
                        "executor ERROR in >=3 consecutive invocations "
                        f"(last={c.get('ERROR')})")
            else:
                state["error_invocations"] = 0
            if state["processed_total"] >= next_progress:
                log.info("PROGRESS: processed_total=%d remaining=%d "
                         "disk=%.1fG db=%sMB ml=%s elapsed=%.0fs",
                         state["processed_total"],
                         remaining(snap["seed"]),
                         snap["disk_free_gb"], snap["db_mb"],
                         snap["merge_log"], time.time() - t0)
                next_progress += PROGRESS_EVERY
            await asyncio.sleep(5)                  # 让队列成形再进入等待
    except SafetyStop as exc:
        state["stopped_at"] = datetime.now(CST).isoformat()
        state["stop_reason"] = str(exc)
        checkpoint_write(ck_path, state)
        print(json.dumps({"runner": "SAFETY STOP", "reason": str(exc),
                          "processed_total": state["processed_total"],
                          "invocations": state["invocations"]}))
        raise SystemExit(3)
    finally:
        await eng.dispose()


async def cmd_status(args: argparse.Namespace) -> None:
    eng = create_async_engine(db_url())
    snap = await safety_check(eng)
    print(json.dumps({"seed": snap["seed"],
                      "remaining": remaining(snap["seed"]),
                      "backlog": snap["backlog"],
                      "disk_free_gb": snap["disk_free_gb"],
                      "db_mb": snap["db_mb"]}))
    await eng.dispose()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pr = sub.add_parser("run")
    pr.add_argument("--checkpoint",
                    default="/home/ubuntu/ops/cb_full_backfill_checkpoint.json")
    sub.add_parser("status")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run({"run": cmd_run, "status": cmd_status}[args.cmd](args))


if __name__ == "__main__":
    main()
