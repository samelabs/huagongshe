#!/usr/bin/env python3
"""E9-B 5: WorkAPI completion receipt 时间保留 executor(P1-5 落地)。

契约:
  - 默认 retention = 30 天(completed_at < now()-30d 的行可删)
  - 默认 batch = 10000, 逐批 DELETE + 逐批 commit(避免单大事务)
  - --dry-run: 只报数零写入
  - 输出: cutoff / candidate count / batch / deleted rows
  - DB 错误非零退出
  - 不记录 token/hash/payload(receipt 行只按 completed_at 寻址)

边界: 只实现 executor; 不建 daemon/service/cron(E10 再接调度)。
不 import WorkAPI transport —— 直接使用 api.core.database 的 engine/session
(settings.database_url), 与 API 进程同一 DSN 口径。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from typing import Any

from sqlalchemy import text

DEFAULT_RETENTION_DAYS = 30
DEFAULT_BATCH = 10000

DELETE_SQL = text("""
    DELETE FROM maintenance.workapi_completion_receipts
    WHERE ctid IN (
        SELECT ctid FROM maintenance.workapi_completion_receipts
        WHERE completed_at < :cutoff
        LIMIT :batch
    )
""")
COUNT_SQL = text("""
    SELECT count(*) FROM maintenance.workapi_completion_receipts
    WHERE completed_at < :cutoff
""")


async def prune(session_factory: Any, *, retention_days: int, batch: int,
                dry_run: bool) -> dict[str, Any]:
    from datetime import datetime, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    out: dict[str, Any] = {
        "cutoff": cutoff.isoformat(), "retention_days": retention_days,
        "batch": batch, "candidates": 0, "deleted": 0, "dry_run": dry_run,
    }
    async with session_factory() as session:
        count_result = await session.execute(COUNT_SQL, {"cutoff": cutoff})
        out["candidates"] = int(count_result.scalar() or 0)
        if dry_run or out["candidates"] == 0:
            return out
        while True:
            result = await session.execute(
                DELETE_SQL, {"cutoff": cutoff, "batch": batch})
            await session.commit()  # 每批一 commit
            out["deleted"] += result.rowcount
            if result.rowcount < batch:
                return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune workapi_completion_receipts older than retention window")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # repo root 上 api/ 可导入(直接脚本运行不经安装)
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from api.core.database import async_session

    try:
        stats = asyncio.run(prune(
            async_session, retention_days=args.retention_days,
            batch=args.batch, dry_run=args.dry_run))
    except Exception as exc:  # noqa: BLE001 — DB 错误非零退出
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"cutoff={stats['cutoff']} retention_days={stats['retention_days']}")
    print(f"candidates={stats['candidates']} batch={stats['batch']}")
    print(f"deleted={stats['deleted']} dry_run={stats['dry_run']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
