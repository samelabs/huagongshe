#!/usr/bin/env python3
"""OAuth 过期凭证定期清理 executor。

无清理任务的后果(审计实证): oauth_authorization_requests / codes /
access_tokens / refresh_tokens 只增不删, 过期凭证无限堆积。

契约(照抄 prune_workapi_receipts 口径):
  - 每张表按"过期/撤销时间 < now() - grace"寻址, 逐批 DELETE + 逐批 commit;
  - grace 默认 7 天 —— 过期/撤销后短窗内保留行, 供 token 端点返回
    标准的 invalid_grant/expired_token 归因与故障调查;
  - --dry-run: 只报数零写入;
  - 输出: cutoff / 各表 candidates / deleted;
  - DB 错误非零退出;
  - 不记录任何 token 明文/hash(行按时间寻址)。

调度: ops/systemd/huagongshe-oauth-prune@.timer 每日执行(grace=7d,
见 docs/DEPLOYMENT.md)。不 import OAuth transport —— 直接使用
api.core.database 的 engine/session, 与 API 进程同一 DSN 口径。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from typing import Any

from sqlalchemy import text

DEFAULT_GRACE_DAYS = 7
DEFAULT_BATCH = 10000

# (表名, 寻址谓词)。access/refresh 按撤销时间同样留 grace 后删
# (撤销 ≠ 立即删除: change_password/停用撤凭证后仍需短窗归因)。
TARGETS: tuple[tuple[str, str], ...] = (
    ("community.oauth_authorization_requests", "expires_at < :cutoff"),
    ("community.oauth_authorization_codes", "expires_at < :cutoff"),
    ("community.oauth_access_tokens",
     "expires_at < :cutoff OR revoked_at < :cutoff"),
    ("community.oauth_refresh_tokens",
     "expires_at < :cutoff OR revoked_at < :cutoff"),
)


async def prune(session_factory: Any, *, grace_days: int, batch: int,
                dry_run: bool) -> dict[str, Any]:
    from datetime import datetime, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=grace_days)
    out: dict[str, Any] = {
        "cutoff": cutoff.isoformat(), "grace_days": grace_days,
        "batch": batch, "dry_run": dry_run, "tables": {},
    }
    async with session_factory() as session:
        for table, predicate in TARGETS:
            count_sql = text(
                f"SELECT count(*) FROM {table} WHERE {predicate}")  # noqa: S608
            delete_sql = text(f"""
                DELETE FROM {table} WHERE ctid IN (
                    SELECT ctid FROM {table}
                    WHERE {predicate}
                    LIMIT :batch
                )
            """)  # noqa: S608
            n = int((await session.execute(
                count_sql, {"cutoff": cutoff})).scalar() or 0)
            stats = {"candidates": n, "deleted": 0}
            if not dry_run and n > 0:
                while True:
                    result = await session.execute(
                        delete_sql, {"cutoff": cutoff, "batch": batch})
                    await session.commit()  # 每批一 commit
                    stats["deleted"] += result.rowcount
                    if result.rowcount < batch:
                        break
            out["tables"][table] = stats
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prune expired/revoked OAuth credentials past grace window")
    parser.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # 参数边界 fail-closed(与 receipt prune 同因): batch<1 会无限空删;
    # grace<1 语义为"删未来才过期的行", 契约外。
    if args.batch < 1:
        parser.error(f"--batch must be >= 1 (got {args.batch})")
    if args.grace_days < 1:
        parser.error(f"--grace-days must be >= 1 (got {args.grace_days})")

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    from api.core.database import async_session

    try:
        stats = asyncio.run(prune(
            async_session, grace_days=args.grace_days,
            batch=args.batch, dry_run=args.dry_run))
    except Exception as exc:  # noqa: BLE001 — DB 错误非零退出
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"cutoff={stats['cutoff']} grace_days={stats['grace_days']} "
          f"batch={stats['batch']} dry_run={stats['dry_run']}")
    total = 0
    for table, tstats in stats["tables"].items():
        print(f"{table}: candidates={tstats['candidates']} "
              f"deleted={tstats['deleted']}")
        total += tstats["deleted"]
    print(f"deleted_total={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
