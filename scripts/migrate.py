#!/usr/bin/env python3
"""§10B forward migration runner(最小实现)。

职责单一: migrations/ 下 forward SQL(YYYYMMDD_NN_description.sql)按
lexicographic 顺序各执行恰好一次, tracking(maintenance.schema_migrations)
记录 filename+sha256, 同事务原子提交。

边界(fail-closed):
  - 只处理 ^\d{8}_\d{2}_[a-z0-9_]+\.sql$; 明确排除 0000/0001/history;
  - 已 applied 文件 hash 变化 → 立即失败, 不执行任何后续;
  - 不解析 SQL: 整文件经 psql 在单事务(-1 / ON_ERROR_STOP)内执行,
    INSERT tracking 与 migration 同一 transaction;
  - advisory lock 防并行 runner。

不引入新 dependency: psql CLI + stdlib。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

FORWARD_RE = re.compile(r"^\d{8}_\d{2}_[a-z0-9_]+\.sql$")
TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS maintenance.schema_migrations (
    filename   text        PRIMARY KEY,
    sha256     text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
"""
# 幂等占位 SELECT: 与真实 migration 一起在同一 psql -1 事务里跑,
# 保证 tracking INSERT 与 DDL 原子。
APPLY_TEMPLATE = "\\i {sqlfile}\nINSERT INTO maintenance.schema_migrations (filename, sha256) VALUES ('{fname}', '{digest}');\n"
LOCK_KEY = 83221010  # huagongshe schema migration runner


def eprint(*a):
    print(*a, file=sys.stderr)


def _psql(database_url: str, sql: str, *, on_error_stop: bool = True,
          single_txn: bool = True) -> subprocess.CompletedProcess:
    """psql 执行; DATABASE_URL 由 libpq 识别(支持 postgres:// 与 postgresql://)。"""
    env = dict(os.environ)
    env["PGOPTIONS"] = "-c statement_timeout=0"
    cmd = ["psql", database_url, "--no-psqlrc", "--quiet",
           "--set", "ON_ERROR_STOP=1", "--command", sql]
    if single_txn:
        cmd.append("--single-transaction")
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    return proc


def run(database_url: str, migrations_dir: str, *,
        apply: bool = True) -> int:
    # 1. 库级 advisory lock(会话级; psql 进程退出即释放)
    proc = _psql(database_url,
                 f"SELECT pg_advisory_lock({LOCK_KEY});")
    if proc.returncode != 0:
        eprint(f"[runner] advisory lock 失败: {proc.stderr.strip()}")
        return 2
    try:
        # 2. tracking table(幂等, 不算 migration)
        proc = _psql(database_url, TRACKING_DDL)
        if proc.returncode != 0:
            eprint(f"[runner] 创建 tracking table 失败: {proc.stderr.strip()}")
            return 2
        # 3. 枚举 + 严格 lexicographic 排序
        files = sorted(
            f for f in os.listdir(migrations_dir)
            if FORWARD_RE.match(f) and os.path.isfile(
                os.path.join(migrations_dir, f))
        )
        # 4. 现有 tracking 记录(-At: 无表头, file|digest 每行)
        proc = subprocess.run(
            ["psql", database_url, "--no-psqlrc", "--quiet", "-At",
             "-c", "SELECT filename, sha256 FROM maintenance.schema_migrations;"],
            env=dict(os.environ), capture_output=True, text=True)
        if proc.returncode != 0:
            eprint(f"[runner] 读 tracking 失败: {proc.stderr.strip()}")
            return 2
        applied: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            line = line.strip()
            if "|" in line:
                fname, digest = line.split("|", 1)
                applied[fname] = digest
        # 5. 逐文件决策 + 原子执行
        for fname in files:
            path = os.path.join(migrations_dir, fname)
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            if fname in applied:
                if applied[fname] != digest:
                    eprint(
                        f"[runner] FAIL-CLOSED: {fname} 已执行但内容变化 "
                        f"(applied={applied[fname][:12]}… now={digest[:12]}…); "
                        f"已执行 migration 视为 immutable, 中止。")
                    return 3
                print(f"[runner] skip {fname} (已执行, hash 一致)")
                continue
            if not apply:
                print(f"[runner] pending {fname}")
                continue
            sql_file = os.path.abspath(path)
            script = APPLY_TEMPLATE.format(
                sqlfile=sql_file, fname=fname, digest=digest)
            # \i + INSERT 同一个 --single-transaction: 原子
            cmd = ["psql", database_url, "--no-psqlrc", "--quiet",
                   "--set", "ON_ERROR_STOP=1", "--single-transaction"]
            env = dict(os.environ)
            env["PGOPTIONS"] = "-c statement_timeout=0"
            proc = subprocess.run(cmd, input=script, env=env,
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                eprint(f"[runner] {fname} 执行失败(已回滚, tracking 未写): "
                       f"{proc.stderr.strip()}")
                return 4
            print(f"[runner] applied {fname} ({digest[:12]}…)")
        return 0
    finally:
        _psql(database_url, f"SELECT pg_advisory_unlock({LOCK_KEY});")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="forward migration runner")
    ap.add_argument("database_url", help="目标库 URL(postgres://…)")
    ap.add_argument("--migrations-dir", default=None,
                    help="migration 根目录(默认: repo migrations/)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只列出 pending, 不执行")
    args = ap.parse_args()
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mdir = args.migrations_dir or os.path.join(root, "migrations")
    return run(args.database_url, mdir, apply=not args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
