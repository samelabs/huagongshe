#!/usr/bin/env python3
"""§10B forward migration runner(最小实现)。

职责单一: migrations/ 下 forward SQL(YYYYMMDD_NN_description.sql)按
lexicographic 顺序各执行恰好一次, tracking(maintenance.schema_migrations)
记录 filename+sha256, 同事务原子提交。

边界(fail-closed):
  - 只处理 ^\\d{8}_\\d{2}_[a-z0-9_]+\\.sql$; 明确排除 0000/0001/history;
  - 已 applied 文件 hash 变化 → 立即失败, 不执行任何后续;
  - 不解析 SQL: 整文件经 psql 在单事务(-1 / ON_ERROR_STOP)内执行,
    INSERT tracking 与 migration 同一 transaction;
  - advisory lock: 一个 persistent psql 子进程在**同一 PostgreSQL session**
    内 pg_advisory_lock → 全程持锁(创建/读取 tracking、hash check、apply 都
    在锁保护下) → 同一 session pg_advisory_unlock 后退出。runner 异常退出时
    psql 进程随 pipe 关闭而终止, PostgreSQL 自动释放 session 级 advisory lock,
    无需恢复状态。

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


def _env() -> dict:
    env = dict(os.environ)
    env["PGOPTIONS"] = "-c statement_timeout=0"
    return env


def _psql(database_url: str, sql: str) -> subprocess.CompletedProcess:
    """一次性 psql 执行(无锁语义, 仅在持锁 session 存活期间调用)。"""
    cmd = ["psql", database_url, "--no-psqlrc", "--quiet",
           "--set", "ON_ERROR_STOP=1", "--single-transaction",
           "--command", sql]
    return subprocess.run(cmd, env=_env(), capture_output=True, text=True)


class _AdvisoryLockHolder:
    """persistent psql session 持锁: lock/unlock 同一 PostgreSQL session。

    psql 以 stdin pipe 模式常驻: 发送 SELECT pg_advisory_lock(...) 并等
    'LOCKED' 回显确认; 全程不关 stdin; 释放时在同一 session 发 unlock。
    进程被杀(pipe 断) → PG 自动释放 session 级 advisory lock。
    """

    def __init__(self, database_url: str, key: int):
        self._url = database_url
        self._key = key
        self._proc: subprocess.Popen | None = None

    def __enter__(self) -> "_AdvisoryLockHolder":
        self._proc = subprocess.Popen(
            ["psql", self._url, "--no-psqlrc", "--quiet", "-X",
             "--set", "ON_ERROR_STOP=1"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=_env())
        # LOCKED 作为确认标记; -A 对齐输出避免表头
        sql = (f"SELECT pg_advisory_lock({self._key});\n"
               f"SELECT 'LOCKED';\n")
        self._proc.stdin.write(sql)
        self._proc.stdin.flush()
        # 读到 LOCKED 行才算拿到锁(阻塞读: pg_advisory_lock 本身会等待)
        got = False
        while True:
            line = self._proc.stdout.readline()
            if not line:
                break
            if line.strip().endswith("LOCKED"):
                got = True
                break
        if not got:
            self._kill()
            raise RuntimeError("advisory lock 未确认(LOCKED 未返回)")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        # 同一 session 显式 unlock, 随后退出
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.write(f"SELECT pg_advisory_unlock({self._key});\n\\q\n")
                self._proc.stdin.flush()
                self._proc.wait(timeout=10)
            except Exception:
                self._kill()
        return False

    def _kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait(timeout=10)


def run(database_url: str, migrations_dir: str, *,
        apply: bool = True) -> int:
    try:
        with _AdvisoryLockHolder(database_url, LOCK_KEY):
            return _run_locked(database_url, migrations_dir, apply=apply)
    except RuntimeError as exc:
        eprint(f"[runner] {exc}")
        return 2


def _run_locked(database_url: str, migrations_dir: str, *,
                apply: bool = True) -> int:
    # 1. tracking table(幂等, 不算 migration; 持锁中执行)
    proc = _psql(database_url, TRACKING_DDL)
    if proc.returncode != 0:
        eprint(f"[runner] 创建 tracking table 失败: {proc.stderr.strip()}")
        return 2
    # 2. 枚举 + 严格 lexicographic 排序
    files = sorted(
        f for f in os.listdir(migrations_dir)
        if FORWARD_RE.match(f) and os.path.isfile(
            os.path.join(migrations_dir, f))
    )
    # 3. 现有 tracking 记录(-At: 无表头, file|digest 每行)
    proc = subprocess.run(
        ["psql", database_url, "--no-psqlrc", "--quiet", "-At",
         "-c", "SELECT filename, sha256 FROM maintenance.schema_migrations;"],
        env=_env(), capture_output=True, text=True)
    if proc.returncode != 0:
        eprint(f"[runner] 读 tracking 失败: {proc.stderr.strip()}")
        return 2
    applied: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if "|" in line:
            fname, digest = line.split("|", 1)
            applied[fname] = digest
    # 4. 逐文件决策 + 原子执行
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
        proc = subprocess.run(cmd, input=script, env=_env(),
                              capture_output=True, text=True)
        if proc.returncode != 0:
            eprint(f"[runner] {fname} 执行失败(已回滚, tracking 未写): "
                   f"{proc.stderr.strip()}")
            return 4
        print(f"[runner] applied {fname} ({digest[:12]}…)")
    return 0


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
