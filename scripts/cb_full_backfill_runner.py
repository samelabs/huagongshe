"""ChemicalBook full-backfill queue-driven runner (0907 v2, one-shot migration tool).

复用 scripts/ops_cb_seed_ingest.py schedule executor, 外层只做控制:
preflight → invoke → wait drain below resume threshold → checkpoint → loop.

0907 v2 控制层修正 (用户令):
  - rolling sustained gate: 最近滚动 1 小时 ledger processed seeds ≤ 3000
    (high_water 管 burst, rolling 管 sustained; executor 参数不变 300/12/2400)
  - 扩展 hard stops: CB 上游 403/429/captcha/timeout趋势、unexpected merge
    delta、PB backlog 持续增长 / final error 累积、persistent ERROR seed
  - checkpoint 扩控制字段; ledger 仍是进度唯一真值
设计铁律:
  - runner 是哑控制层: 不碰 identity/queue/worker 机制。
  - 安全重启: 进度真值 = ingestion.chemicalbook_seed ledger。
  - 硬停即退出不自动恢复; 完成后退出, 不 cron / 不 systemd / 不常驻。
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

import sys  # noqa: E402
if "/var/www/huagongshe" not in sys.path:
    sys.path.insert(0, "/var/www/huagongshe")

log = logging.getLogger("hgs.ingest.cb_runner")

EXECUTOR = ["/var/www/huagongshe/venv/bin/python",
            "scripts/ops_cb_seed_ingest.py"]
CST = timezone(timedelta(hours=8))
WORKER_LOG = "/home/ubuntu/.pm2/logs/huagongshe-pubchem-worker-error.log"

# 冻结参数: executor 300/h, 12h backlog, high_water 2400; resume <500
THROUGHPUT = 300
BACKLOG_HOURS = 12
HIGH_WATER = 2400
RESUME_THRESHOLD = 500
INVOKE_LIMIT = 50_000
DISK_MIN_FREE_GB = 25.0
DISK_MAX_USAGE = 85.0
WAIT_POLL_S = 60
PROGRESS_EVERY = 50_000

# 0907 v2: rolling sustained gate (ledger processed seeds, 非 jobs)
MAX_PROCESSED_PER_HOUR = 3000
ROLLING_WINDOW_S = 3600

# CB 上游风控信号 (worker log: caslib.fetch state=error 且 status=4xx/5xx;
# 404=真实缺页不算)。captcha/anti-bot 目前 fetch 层无此状态, 若未来出现
# status=200 state=error(alien_page) 连续趋势也纳入。
UPSTREAM_FATAL_STATUS = ("403", "429")
UPSTREAM_TREND_LIMIT = 20          # 窗口内 timeout/reset 类 error 条数阈值
UPSTREAM_WINDOW_LINES = 2000       # 扫描最近日志行数

# PB sustained 监控 (偶发 503 不停)
PB_BACKLOG_GROW_CYCLES = 5         # 连续 N 个检查周期 queued 只增不降
PB_ERROR_LIMIT = 100               # final error 累积阈值

# persistent ERROR seed: 现有 attempts 上限口径 (不新增终态 schema)
SEED_MAX_ATTEMPTS = 10

ACTIVE_STATUSES = ("ACCEPTED", "PENDING_NEW", "ERROR")
# Gov 正式可解释 merge reason 模式 (identity.py _absorb_verified 落表值)
KNOWN_MERGE_REASON_PATTERNS = (
    re.compile(r"^prod-batch-2864 \| gate=same-cid:\d+$"),
)


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


# ---------------------------------------------------------------- rolling

class RollingGate:
    """滚动 1h processed seeds 限制 (进程内窗口; restart 后从 checkpoint
    的 history 事件恢复, 不丢已消费额度)。"""

    def __init__(self, events: list | None = None):
        # events: [[epoch_ts, processed], ...]
        self.events = list(events or [])

    def add(self, processed: int, ts: float | None = None) -> None:
        if processed > 0:
            self.events.append([ts or time.time(), processed])

    def sum_last_hour(self, now: float | None = None) -> int:
        now = now or time.time()
        self.events = [e for e in self.events if now - e[0] < ROLLING_WINDOW_S]
        return sum(e[1] for e in self.events)

    def blocked(self, now: float | None = None) -> bool:
        return self.sum_last_hour(now) >= MAX_PROCESSED_PER_HOUR

    def next_release_s(self, now: float | None = None) -> float:
        """窗口内最早事件滑出窗口还需多久 (额度释放时间)。"""
        now = now or time.time()
        self.events = [e for e in self.events if now - e[0] < ROLLING_WINDOW_S]
        if self.sum_last_hour(now) < MAX_PROCESSED_PER_HOUR:
            return 0.0
        # 需要释放的最小额度: 按事件时间序逐个滑出
        need = self.sum_last_hour(now) - MAX_PROCESSED_PER_HOUR + 1
        acc = 0
        for ts, n in sorted(self.events):
            acc += n
            if acc >= need:
                return max(0.0, ts + ROLLING_WINDOW_S - now)
        return WAIT_POLL_S

    def snapshot(self) -> list:
        return [[round(e[0], 3), e[1]] for e in self.events]


# ---------------------------------------------------------------- checks

def check_upstream_log() -> dict:
    """扫 worker 日志最近窗口: CB 上游 403/429/captcha/timeout 趋势。
    只统计 caslib.fetch cas/cpp 行 (CB 链); PB 503 单独由 PB 监控管。"""
    counts = {"cb_403": 0, "cb_429": 0, "cb_timeout": 0, "cb_reset": 0,
              "captcha": 0, "alien": 0}
    try:
        with open(WORKER_LOG, "r", errors="replace") as f:
            lines = f.readlines()[-UPSTREAM_WINDOW_LINES:]
    except OSError:
        return counts                     # 日志不可读不视为安全信号
    for ln in lines:
        if "caslib.fetch" not in ln:
            continue
        if "state=error" not in ln:
            continue
        m = re.search(r"status=(\d+)", ln)
        status = m.group(1) if m else ""
        if status in UPSTREAM_FATAL_STATUS:
            counts[f"cb_{status}"] += 1
        elif "timeout" in ln.lower() or "timed out" in ln.lower():
            counts["cb_timeout"] += 1
        elif "reset" in ln.lower():
            counts["cb_reset"] += 1
        elif status == "200" and "alien_page" in ln:
            counts["alien"] += 1
        if "captcha" in ln.lower() or "anti-bot" in ln.lower():
            counts["captcha"] += 1
    if counts["cb_403"] > 0 or counts["cb_429"] > 0 or counts["captcha"] > 0:
        raise SafetyStop(f"CB upstream risk control: {counts}")
    trend = counts["cb_timeout"] + counts["cb_reset"] + counts["alien"]
    if trend >= UPSTREAM_TREND_LIMIT:
        raise SafetyStop(f"CB upstream error trend: {counts}")
    return counts


async def safety_check(eng, state: dict | None = None) -> dict:
    """单一硬停检查点; 返回快照, 异常即停。state 用于 Gov baseline。"""
    free_gb, usage = disk_state()
    if free_gb < DISK_MIN_FREE_GB:
        raise SafetyStop(f"disk free {free_gb:.2f}GB < {DISK_MIN_FREE_GB}GB")
    if usage >= DISK_MAX_USAGE:
        raise SafetyStop(f"disk usage {usage:.2f}% >= {DISK_MAX_USAGE}%")
    check_upstream_log()                  # CB 上游风控 (硬停在此抛出)
    async with eng.connect() as db:
        await db.execute(text("SET statement_timeout='300s'"))
        await db.commit()
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
        dup_nn = (await db.execute(text(
            "SELECT count(*) FROM (SELECT 1 FROM chemistry.chemical_cb"
            " WHERE cb_number IS NOT NULL GROUP BY chemical_id, cb_number,"
            " locale HAVING count(*) > 1) t"))).scalar()
        if dup_nn > 0:
            raise SafetyStop(f"duplicate nonnull grain = {dup_nn}")
        dup_null = (await db.execute(text(
            "SELECT count(*) FROM (SELECT 1 FROM chemistry.chemical_cb"
            " WHERE cb_number IS NULL GROUP BY chemical_id, source_url,"
            " locale HAVING count(*) > 1) t"))).scalar()
        if dup_null > 0:
            raise SafetyStop(f"duplicate null grain = {dup_null}")
        dang = (await db.execute(text(
            "SELECT count(*) FROM (SELECT DISTINCT chemical_id"
            " FROM chemistry.chemical_cb ORDER BY chemical_id DESC"
            " LIMIT 200) s WHERE NOT EXISTS (SELECT 1 FROM"
            " chemistry.chemicals m WHERE m.id = s.chemical_id)"))).scalar()
        if dang > 0:
            raise SafetyStop(f"dangling FK sample = {dang}")
        # Gov: 新 merge 必须可解释 (已知正式 reason 模式)
        if state is not None:
            base = state.get("merge_baseline")
            if base is not None and snap["merge_log"] > base:
                new_reasons = (await db.execute(text(
                    "SELECT reason FROM maintenance.identity_merge_log"
                    " WHERE merge_id > :max_id ORDER BY merge_id"
                    " LIMIT 50"), {"max_id": state["merge_max_id"]})).fetchall()
                for (reason,) in new_reasons:
                    if not any(p.match(reason or "")
                               for p in KNOWN_MERGE_REASON_PATTERNS):
                        raise SafetyStop(
                            "unexplained merge delta: "
                            f"reason={reason!r} not in known gates")
                state["merge_max_id"] = base and snap.get(
                    "merge_max_id") or state["merge_max_id"]
        # persistent ERROR seed: attempts 达上限仍 ERROR → 报告停
        stuck = (await db.execute(text(
            "SELECT cb_number, cas, attempts, left(last_error,120)"
            " FROM ingestion.chemicalbook_seed"
            " WHERE status='ERROR' AND attempts >= :lim"
            " ORDER BY updated_at DESC LIMIT 5"),
            {"lim": SEED_MAX_ATTEMPTS})).fetchall()
        if stuck:
            detail = "; ".join(f"cb={r[0]} cas={r[1]} attempts={r[2]}"
                               f" err={r[3]}" for r in stuck)
            raise SafetyStop(f"persistent ERROR seed at attempts limit: "
                             f"{detail}")
        snap["db_mb"] = (await db.execute(text(
            "SELECT pg_database_size('huagongshe')/1024/1024"))).scalar()
        snap["pb_queued"] = (await db.execute(text(
            "SELECT count(*) FROM maintenance.pubchem_jobs"
            " WHERE status='queued'"))).scalar()
        snap["pb_error"] = (await db.execute(text(
            "SELECT count(*) FROM maintenance.pubchem_jobs"
            " WHERE status='error'"))).scalar()
    snap["disk_free_gb"] = round(free_gb, 2)
    snap["disk_usage"] = round(usage, 2)
    return snap


def remaining(seed: dict) -> int:
    return sum(seed.get(s, 0) for s in ACTIVE_STATUSES)


async def wait_drain(eng, gate: RollingGate, state: dict) -> int:
    """等 cas_jobs < RESUME_THRESHOLD; 期间保持全部硬停检查 + rolling 检查。"""
    t0 = time.time()
    pb_queued_hist: list[int] = []
    while True:
        snap = await safety_check(eng, state)     # 磁盘/上游/Gov 全量硬停
        pb_queued_hist.append(snap["pb_queued"])
        if len(pb_queued_hist) > PB_BACKLOG_GROW_CYCLES:
            pb_queued_hist.pop(0)
            window = pb_queued_hist[:]
            if all(later > earlier for earlier, later
                   in zip(window, window[1:])):
                raise SafetyStop("PB backlog sustained growth: "
                                 f"{window}")
        if snap["pb_error"] >= PB_ERROR_LIMIT:
            raise SafetyStop(f"PB final error accumulating: "
                             f"{snap['pb_error']} >= {PB_ERROR_LIMIT}")
        if snap["backlog"] < RESUME_THRESHOLD:
            return int(time.time() - t0)
        if gate.blocked():
            log.info("rolling gate holding during drain: 1h=%d/%d",
                     gate.sum_last_hour(), MAX_PROCESSED_PER_HOUR)
        await asyncio.sleep(WAIT_POLL_S)


def invoke_executor() -> dict:
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
    # restart 恢复: rolling 窗口从 checkpoint history 重建
    prev = {}
    if os.path.exists(ck_path):
        try:
            prev = json.load(open(ck_path))
        except (json.JSONDecodeError, OSError):
            prev = {}
    hist_events = [e for e in prev.get("rolling_events", [])]
    gate = RollingGate(hist_events)
    state = {"runner_started_at": datetime.now(CST).isoformat(),
             "invocations": prev.get("invocations", 0),
             "processed_total": prev.get("processed_total", 0),
             "history": prev.get("history", [])[-50:],
             "safety_status": "RUNNING"}
    # Gov baseline (启动时固化; 重启后沿用既有 baseline 的 max_id)
    async with eng.connect() as db:
        await db.execute(text("SET statement_timeout='300s'"))
        state["merge_baseline"] = (await db.execute(text(
            "SELECT count(*) FROM maintenance.identity_merge_log"))).scalar()
        state["merge_max_id"] = (await db.execute(text(
            "SELECT coalesce(max(merge_id),0) FROM"
            " maintenance.identity_merge_log"))).scalar()
        await db.commit()
    log.info("runner start; ledger 为进度真值, checkpoint=%s merge_baseline=%s",
             ck_path, state["merge_baseline"])
    next_progress = PROGRESS_EVERY * (
        state["processed_total"] // PROGRESS_EVERY + 1)
    t0 = time.time()
    try:
        while True:
            snap = await safety_check(eng, state)
            rem = remaining(snap["seed"])
            state.update({"rolling_1h_processed": gate.sum_last_hour(),
                          "last_invocation_at":
                              (state["history"][-1]["ts"]
                               if state["history"] else None),
                          "current_queue": snap["backlog"],
                          "disk_free": snap["disk_free_gb"],
                          "merge_log_count": snap["merge_log"],
                          "redirect_count": snap["redirect"]})
            checkpoint_write(ck_path, state)
            log.info("preflight: remaining=%d backlog=%d roll1h=%d/%d "
                     "disk=%.1fG/%.1f%% ml=%s", rem, snap["backlog"],
                     gate.sum_last_hour(), MAX_PROCESSED_PER_HOUR,
                     snap["disk_free_gb"], snap["disk_usage"],
                     snap["merge_log"])
            if rem == 0 and snap["backlog"] < RESUME_THRESHOLD:
                log.info("eligible exhausted; final drain wait")
                await wait_drain(eng, gate, state)
                snap2 = await safety_check(eng, state)
                if remaining(snap2["seed"]) == 0:
                    state["finished_at"] = datetime.now(CST).isoformat()
                    state["safety_status"] = "COMPLETE"
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
                w = await wait_drain(eng, gate, state)
                log.info("drained in %ds; continue", w)
                continue
            if gate.blocked():
                # sustained gate: 不注入, 等窗口释放
                rel = gate.next_release_s()
                log.info("rolling gate HOLD: 1h=%d >= %d; release in %.0fs",
                         gate.sum_last_hour(), MAX_PROCESSED_PER_HOUR, rel)
                await asyncio.sleep(max(WAIT_POLL_S, min(rel, 600)))
                continue
            # ---- invocation ----
            payload = invoke_executor()
            state["invocations"] += 1
            state["processed_total"] += payload.get("processed", 0)
            gate.add(payload.get("processed", 0))
            state["rolling_events"] = gate.snapshot()
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
                         state["processed_total"], rem,
                         snap["disk_free_gb"], snap["db_mb"],
                         snap["merge_log"], time.time() - t0)
                next_progress += PROGRESS_EVERY
            await asyncio.sleep(5)
    except SafetyStop as exc:
        state["stopped_at"] = datetime.now(CST).isoformat()
        state["stop_reason"] = str(exc)
        state["safety_status"] = "HARD_STOP"
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
                      "db_mb": snap["db_mb"],
                      "pb_queued": snap.get("pb_queued"),
                      "pb_error": snap.get("pb_error")}))
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
