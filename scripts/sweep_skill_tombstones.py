#!/usr/bin/env python3
"""P2c(审计): 技能删除 tombstone 残留清扫 executor。

delete lifecycle 的补偿路径会留下 `.deleted-{skill_id}-{uuid}` tombstone
(PURGE_FAILED / 进程崩溃时的原子的 rename 中间态)。无清扫机制时它们
永久堆积在 skill_root。

契约:
  - 只扫 settings.skill_root 下一层 `.deleted-*` 目录(不递归、不碰 canonical);
  - 默认 grace = 7 天, 按目录 mtime 判断(rename 保留原 mtime, 刚删除的老目录
    可能立即超窗 —— 不与删除操作同时手动执行);
  - --dry-run: 只报数零删除;
  - 输出: root / candidates / deleted / kept_fresh;
  - FS 错误非零退出。

调度: ops/systemd/huagongshe-skill-tombstone-sweep@.timer 每日执行
(grace=7d, 见 docs/DEPLOYMENT.md)。
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

DEFAULT_GRACE_DAYS = 7


def sweep(root: Path, *, grace_days: int, dry_run: bool) -> dict[str, int | str]:
    import shutil
    import time
    cutoff = time.time() - timedelta(days=grace_days).total_seconds()
    out: dict[str, int | str] = {
        "root": str(root), "grace_days": grace_days,
        "dry_run": dry_run, "candidates": 0, "deleted": 0, "kept_fresh": 0,
    }
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not entry.name.startswith(".deleted-"):
            continue
        out["candidates"] = int(out["candidates"]) + 1
        try:
            mtime = entry.stat().st_mtime
        except FileNotFoundError:
            continue  # 并发清理竞态: 已不在, 计入下一次
        if mtime >= cutoff:
            out["kept_fresh"] = int(out["kept_fresh"]) + 1
            continue
        if not dry_run:
            shutil.rmtree(entry)
            out["deleted"] = int(out["deleted"]) + 1
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sweep stale skill-delete tombstones under skill_root")
    parser.add_argument("--grace-days", type=int, default=DEFAULT_GRACE_DAYS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.grace_days < 1:
        parser.error(f"--grace-days must be >= 1 (got {args.grace_days})")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from api.core.config import settings

    try:
        stats = sweep(Path(settings.skill_root),
                      grace_days=args.grace_days, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 — FS 错误非零退出
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"root={stats['root']} grace_days={stats['grace_days']} "
          f"dry_run={stats['dry_run']}")
    print(f"candidates={stats['candidates']} deleted={stats['deleted']} "
          f"kept_fresh={stats['kept_fresh']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
