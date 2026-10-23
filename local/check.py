#!/usr/bin/env python3
"""HGS 仓库检查编排器 — 仓库根统一检查入口。

权威运行手册: docs/TESTING.md。本文件只用宿主 Python 标准库做编排,
真正的检查仍由既有工具承担(容器内 unittest / 宿主 Node 的 npm 脚本)。

子命令:
  preflight   只读环境盘点(不写库、不杀进程、不装包、不打印秘密)
  web         宿主 Node: tsc + test:unit + test:locale + check:api-layer(默认不 build)
  backend     容器内非 root 跑显式最小后端模块集, 每 run 专有测试库
  worker      一次性干净 venv 只装 requirements-worker.txt 并跑 worker 导入检查
  release     显式发布门禁(冻结 SHA、阶段化; --dry-run 只列计划)

退出码: 0=PASS  1=FAIL(断言/命令失败)  2=BLOCKED(环境或依赖未就绪)
        3=用法错误(含空选择、非法模块名、错误 cwd)

run 产物目录 local/.check-runs/<run_id>/(不入 git): 每步 stdout/stderr
日志(脱敏)、result.json(结构化结果)。凭据只从 local/stack/.env.local
读入内存, 不写入任何日志或结果文件; 日志里的连接串一律去密码。
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import json
import hashlib
import signal
import shlex
import traceback
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "local"))
import next_lock

RUNS_DIR = os.path.join(ROOT, "local", ".check-runs")
STACK_ENV_FILE = os.path.join(ROOT, "local", "stack", ".env.local")
DEV_MARKER = os.path.join(ROOT, "local", ".dev-active.json")
BUILD_MARKER = os.path.join(ROOT, "local", ".check-runs", "build-active.json")
REDIS_LOCK_FILE = os.path.join(tempfile.gettempdir(), "hgs-check-redis-db15.lock")
BUILD_LOCK_FILE = os.path.join(RUNS_DIR, "next-output.lock")
_ACTIVE_RUN = None

API_CONTAINER = "hgs_local_api"
DB_CONTAINER = "hgs_local_db"
REDIS_CONTAINER = "hgs_local_redis"
TESTER_USER = "tester"
VENV_PYTHON = "/opt/venv/bin/python"

TEST_REDIS_URL = "redis://redis:6379/15"
CANONICAL_BASE_URL = "https://huagongshe.com"
DB_SENTINEL = "hgs-test-db"
SENTINELED_SCHEME = "postgresql+asyncpg://"
NATIVE_SCHEME = "postgresql://"

EXIT_PASS, EXIT_FAIL, EXIT_BLOCKED, EXIT_USAGE = 0, 1, 2, 3

# 与 tests/db_gate.py 的库名闸同构: run 专有库必须落在允许名单内
RUN_DB_NAME_RE = re.compile(r"^test_hgs_[a-z0-9]{8}$")
TEST_MODULE_RE = re.compile(r"^tests\.[a-z0-9_]+$")
_URL_SECRET_RE = re.compile(r"://([^:/@\s]+):([^@\s]+)@")
_ENV_SECRET_RE = re.compile(r"\b(PGPASSWORD=)[^\s]+")
_RAN_RE = re.compile(r"^Ran (\d+) tests? in ", re.M)
# unittest -v 对带 docstring 的用例输出两行("name (id)" 换行 "docstring 首行 ... 结果"),
# 单行与两行形态同一口径计入。
_DOC_LINE = r"(?:\n[^\n]*?)?"
_SKIP_LINE_RE = re.compile(
    r"^(test_\S+|runTest|setUpClass|tearDownClass|setUpModule|tearDownModule) \(([^)]+)\)"
    + _DOC_LINE + r" \.\.\. skipped ['\"]?(.*?)['\"]?\s*$", re.M)
_XFAIL_LINE_RE = re.compile(
    r"^(test_\S+|runTest) \(([^)]+)\)" + _DOC_LINE + r" \.\.\. expected failure", re.M)
_TAIL_RE = re.compile(r"^(OK|FAILED)\b(?:\s*\((.*)\))?\s*$", re.M)


class BlockedError(RuntimeError):
    """环境或依赖未就绪 — 记 BLOCKED, 不触库不留残留。"""


class FailError(RuntimeError):
    """检查真实失败 — 记 FAIL。"""


class UsageError(RuntimeError):
    """用法错误 — 退出码 3。"""


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_RUN_SECRETS = set()

# 遮蔽串程序拼装, 源码不携带字面量 —— 与 tests/test_mcp_governance 的
# 占位符卫生约定同一手法(仓库文本禁止出现三星遮蔽字面量)。
_MASK = chr(42) * 3


def redact(text: str) -> str:
    """连接串密码段与 PGPASSWORD 注入值替换为三星遮蔽(日志与结果统一出口)。"""
    for secret in sorted(_RUN_SECRETS, key=len, reverse=True):
        text = text.replace(secret, _MASK)
    return _ENV_SECRET_RE.sub(r"\1" + _MASK, _URL_SECRET_RE.sub(r"://\1:" + _MASK + "@", text))


def safe_value(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {redact(str(k)): safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(v) for v in value]
    return value


def parse_db_url(url: str) -> dict:
    """解析标准 URL 取身份四元组; 解析失败抛 ValueError。

    scheme 允许差异(postgresql 与 postgresql+asyncpg 同库), query 里的
    test_sentinel 不参与身份比较。
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("postgresql", "postgresql+asyncpg"):
        raise ValueError(f"不支持的 scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise ValueError("URL 缺少 host")
    dbname = parts.path.lstrip("/").split("?")[0]
    if not dbname:
        raise ValueError("URL 缺少数据库路径")
    return {"username": parts.username or "", "host": parts.hostname,
            "port": parts.port or 5432, "database": dbname}


class EnvTargetMismatch(RuntimeError):
    """TEST/HGS 两个数据库 URL 指向不一致 — 连接前拒绝。"""


def assert_same_target(test_url: str, app_url: str) -> None:
    """测试子进程环境一致性: 两个 URL 必须同 host/port/username/database。

    允许 scheme 与 sentinel query 差异; 其余任何不一致在此抛错,
    早于任何连接或 DDL。
    """
    a, b = parse_db_url(test_url), parse_db_url(app_url)
    for key in ("host", "port", "username", "database"):
        if a[key] != b[key]:
            raise EnvTargetMismatch(
                f"数据库目标不一致({key}): TEST={a[key]!r} HGS={b[key]!r}; "
                "测试子进程必须指向同一专有测试库, 拒绝执行。")


def new_run_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    return f"{stamp}-{secrets.token_hex(3)}"


def run_db_name() -> str:
    """run 专有库名: 随机后缀, 必须落在 db_gate 库名模式内。"""
    name = "test_hgs_" + secrets.token_hex(4)
    if not RUN_DB_NAME_RE.match(name):
        raise ValueError(f"生成的库名 {name!r} 不符合 run 专有库模式")
    return name


def build_test_urls(user: str, password: str, host: str, port: int, dbname: str):
    """构造同库的 TEST/HGS 两个 URL(TEST 带 sentinel)并预检一致性。"""
    cred = f"{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(password, safe='')}@{host}:{port}/{dbname}"
    test_url = f"{SENTINELED_SCHEME}{cred}?test_sentinel={DB_SENTINEL}"
    app_url = f"{SENTINELED_SCHEME}{cred}"
    assert_same_target(test_url, app_url)
    sys.path.insert(0, ROOT) if ROOT not in sys.path else None
    from tests.db_gate import require_test_db
    require_test_db(test_url)
    if not RUN_DB_NAME_RE.fullmatch(dbname):
        raise EnvTargetMismatch("目标不是本 run 专有库")
    return test_url, app_url, f"{NATIVE_SCHEME}{cred}"


def load_stack_env() -> dict:
    """读 local/stack/.env.local; 只取编排需要的键, 值不外印。"""
    values = {}
    with open(STACK_ENV_FILE, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    for key in ("HGS_DB_USER", "HGS_DB_PASSWORD"):
        if not values.get(key):
            raise BlockedError(f"{STACK_ENV_FILE} 缺少 {key}: 本地栈未初始化, 见 local/README.md")
    for key, value in values.items():
        if value and ("PASSWORD" in key or "SECRET" in key or key.startswith("SEED_HGS_")):
            _RUN_SECRETS.update((value, urllib.parse.quote(value, safe="")))
    return values


# ─── dev 与 production build 的互斥(同一 checkout 不共用 .next 产物) ───

def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_marker(path: str):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and int(data.get("pid", 0)) > 0 else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        raise BlockedError(f"互斥标记无法确认: {path}") from exc


def write_marker(path: str, kind: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"kind": kind, "pid": os.getpid(), "started": now_iso()}, fh)


def remove_marker(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def dev_build_decision(dev_marker: str, build_marker: str, alive=pid_alive):
    """dev 与 build 的互斥判定, 供编排器与 local/dev.sh 共用语义。

    返回 (action, message): action ∈ ok / dev_active / build_active /
    stale — stale 表示发现死进程残留标记(可安全清理后继续)。
    """
    dev = read_marker(dev_marker)
    if dev and alive(int(dev["pid"])):
        return "dev_active", (
            f"next dev 正在运行(pid {dev['pid']}, {dev_marker}); 同一 "
            "checkout 的 production build 会覆盖 dev 产物。先停 "
            "local/dev.sh 或改用隔离 checkout。")
    build = read_marker(build_marker)
    if build and alive(int(build["pid"])):
        return "build_active", (
            f"production build 正在运行(pid {build['pid']}); 此时启动 dev "
            "会读到半成品产物, 稍后再试。")
    stale = [p for p, m in ((dev_marker, dev), (build_marker, build)) if m]
    if stale:
        return "stale", "发现死进程残留标记, 可清理: " + ", ".join(stale)
    return "ok", "无 dev/build 冲突"


# ─── unittest 输出解析与定级(纯函数, 供保护测试) ───

def _case_id(paren: str, name: str) -> str:
    """括号内已是完整 id(含方法名)则直接用, 否则补方法名。"""
    return paren if paren.endswith("." + name) else f"{paren}.{name}"


def parse_unittest_output(text: str) -> dict:
    ran_matches = list(_RAN_RE.finditer(text))
    tail_matches = list(_TAIL_RE.finditer(text))
    ran = ran_matches[-1] if ran_matches else None
    tail = tail_matches[-1] if tail_matches else None
    counts = {"failures": 0, "errors": 0, "skipped": 0,
              "expected failures": 0, "unexpected successes": 0}
    status = None
    if tail:
        status = tail.group(1)
        for item in filter(None, (tail.group(2) or "").split(", ")):
            key, _, num = item.partition("=")
            if key.strip() in counts and num.strip().isdigit():
                counts[key.strip()] = int(num.strip())
    skips = [f"{_case_id(m.group(2), m.group(1))}: {m.group(3)}"
             for m in _SKIP_LINE_RE.finditer(text)]
    xfails = [_case_id(m.group(2), m.group(1))
              for m in _XFAIL_LINE_RE.finditer(text)]
    return {"ran": int(ran.group(1)) if ran else 0, "status": status,
            "counts": counts, "skip_details": skips, "xfail_details": xfails}


def verdict(parsed: dict, allowed_skips=(), allowed_xfails=()) -> dict:
    """定级 PASS/FAIL: 空选择、失败、未许可 skip 都不得为 PASS。"""
    allowed = set(allowed_skips)
    if parsed.get("status") != "OK":
        return {"status": "FAIL", "reason": "unittest 未完整成功结束"}
    if parsed["counts"]["skipped"] != len(parsed["skip_details"]):
        return {"status": "FAIL", "reason": "skip 统计与逐项记录不一致"}
    if parsed["counts"]["expected failures"] != len(parsed["xfail_details"]):
        return {"status": "FAIL", "reason": "xfail 统计与逐项记录不一致"}
    if parsed["ran"] == 0:
        return {"status": "FAIL", "reason": "选择被执行的用例为 0: 空选择不得记为通过"}
    bad = {k: v for k, v in parsed["counts"].items()
           if k in ("failures", "errors", "unexpected successes") and v}
    if bad:
        return {"status": "FAIL", "reason": f"unittest 统计失败项: {bad}"}
    if any(case not in set(allowed_xfails) for case in parsed["xfail_details"]):
        return {"status": "FAIL", "reason": "存在未许可的 expected failure"}
    skipped = parsed["counts"]["skipped"]
    if skipped:
        unexpected = [s for s in parsed["skip_details"]
                      if s.split(":", 1)[0] not in allowed]
        if unexpected:
            return {"status": "FAIL",
                    "reason": f"存在未许可的 skip({len(unexpected)} 项)",
                    "details": unexpected}
    return {"status": "PASS",
            "reason": (f"{skipped} 项 skip 均为许可项" if skipped else ""),
            "details": parsed["skip_details"]}


def cleanup_resources(registry, executor):
    """只清理本 run 登记过的资源; executor(kind, ident) -> (ok, error)。

    失败不互相阻断, 逐项记录清理状态与残留位置。
    """
    results = []
    for item in registry:
        try:
            ok, err = executor(item["kind"], item["ident"])
        except Exception as exc:  # noqa: BLE001 — 清理失败逐项落账, 不吞
            ok, err = False, f"{type(exc).__name__}: {exc}"
        results.append({"kind": item["kind"], "ident": redact(str(item["ident"])),
                        "cleaned": bool(ok), "error": err})
    return results


# ─── run 记录与子进程 ───

class Run:
    def __init__(self, name: str):
        global _ACTIVE_RUN
        self.run_id = new_run_id()
        self.name = name
        self.dir = os.path.join(RUNS_DIR, self.run_id)
        os.makedirs(self.dir, exist_ok=True)
        _ACTIVE_RUN = self
        self.started = now_iso()
        self.processes_stopped = True
        self.steps = []
        self.registry = []       # 本 run 创建的资源(清理只认这份登记)
        self.context = {}
        self.cleanup_results = []
        self._seq = 0

    def info(self, key, value):
        self.context[key] = value

    def step(self, step: dict):
        self.steps.append(step)
        return step

    def exec(self, name, cmd, *, timeout=600, env=None, cwd=None):
        """Keep local and container process groups owned until they stop."""
        self._seq += 1
        base = os.path.join(self.dir, f"{self._seq:02d}_{name}")
        original = list(cmd)
        remote = None
        token = f"{self.run_id}-{self._seq}"
        if cmd[:2] == ["docker", "exec"]:
            for container in (API_CONTAINER, DB_CONTAINER):
                if container in cmd:
                    i = cmd.index(container)
                    remote = container
                    cmd = cmd[:i+1] + ["bash", "/repo/local/run_step.sh", token,
                                      str(timeout)] + cmd[i+1:]
                    break
        started = now_iso()
        execution_started = time.monotonic()
        deadline = timeout + 10 if remote else timeout
        code, timed_out, launch_error = None, False, None
        stdout = stderr = ""
        proc = None
        try:
            proc = subprocess.Popen(cmd, env=env, cwd=cwd, start_new_session=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    pass_fds=next_lock.held_fds())
            out, err = proc.communicate(timeout=deadline)
            code = proc.returncode
            timed_out = remote is not None and (code == 124 or (code == 137 and time.monotonic() - execution_started >= timeout))
            stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            timed_out = isinstance(exc, subprocess.TimeoutExpired)
            if remote:
                try:
                    stopped = subprocess.run(
                        ["docker", "exec", remote, "bash", "/repo/local/run_step.sh", "--stop", token],
                        capture_output=True, timeout=15).returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    stopped = False
                self.processes_stopped = self.processes_stopped and stopped
                if not stopped:
                    with open(REDIS_LOCK_FILE + ".unsafe", "w") as fh:
                        json.dump({"run": self.run_id, "container": remote, "step": token}, fh)
            if proc:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    if proc.poll() is not None:
                        break
                    try:
                        os.killpg(proc.pid, sig)
                    except PermissionError:
                        try:
                            proc.send_signal(sig)
                        except PermissionError as exc:
                            self.processes_stopped = False
                            raise BlockedError("无法终止宿主子进程；资源保留待处理") from exc
                        except ProcessLookupError:
                            pass
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        continue
                try:
                    out, err = proc.communicate(timeout=3)
                except subprocess.TimeoutExpired as exc:
                    self.processes_stopped = False
                    raise BlockedError("宿主子进程未停止，保留资源待处理") from exc
                stdout, stderr = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
            if not self.processes_stopped:
                raise BlockedError("无法确认远程进程停止；资源保留，禁止并发测试")
            if not timed_out:
                raise BlockedError("检查被中断；本 run 进程已停止")
            stderr += f"\n[check.py] 超时 {timeout}s，本 run 进程组已终止\n"
        except OSError as exc:
            launch_error = str(exc)
            stderr = launch_error
        finally:
            for suffix, value in ((".out", stdout), (".err", stderr)):
                with open(base + suffix, "w", encoding="utf-8") as fh:
                    fh.write(redact(value))
            self.step({"name": name, "exit_code": code, "timed_out": timed_out,
                       "cmd": redact(" ".join(original)), "cwd": cwd or os.getcwd(),
                       "started": started, "finished": now_iso()})
        if launch_error:
            raise BlockedError("无法执行检查: " + launch_error)
        return code, timed_out, stdout, stderr

    def docker(self, name, args, *, timeout=600, env=None):
        return self.exec(name, ["docker", *args], timeout=timeout, env=env)

    def finish(self, overall: str, message: str) -> int:
        if overall == "PASS" and any(not r["cleaned"] for r in self.cleanup_results):
            overall, message = "BLOCKED", "检查已执行，但资源清理未完成"
        result = {
            "run_id": self.run_id, "command": self.name,
            "started": self.started, "finished": now_iso(),
            "cwd": self.context.get("invoked_cwd", os.getcwd()),
            "head": self.context.get("head"),
            "dirty": self.context.get("dirty"),
            "working_tree_evidence": bool(self.context.get("dirty")),
            "environment": self.context, "steps": self.steps,
            "cleanup": self.cleanup_results,
            "overall": overall, "message": message,
        }
        path = os.path.join(self.dir, "result.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(safe_value(result), fh, ensure_ascii=False, indent=2)
        print(redact(f"[check.py] overall={overall} {message}"))
        print(f"[check.py] 结果与日志: {path}")
        return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL,
                "BLOCKED": EXIT_BLOCKED}[overall]


def git_snapshot(run: Run):
    head = None
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                capture_output=True,
                                text=True).stdout.splitlines()
    except OSError:
        status = []
    run.info("head", head)
    run.info("dirty", [line for line in status if line.strip()])
    return head, status


def source_fingerprint():
    result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
                            cwd=ROOT, capture_output=True, check=True)
    digest = hashlib.sha256()
    for raw in sorted(set(result.stdout.split(b"\0")) - {b""}):
        name = os.fsdecode(raw)
        if name.startswith("docs/"):
            continue
        path = os.path.join(ROOT, name)
        digest.update(raw + b"\0")
        try:
            with open(path, "rb") as fh:
                digest.update(fh.read())
        except FileNotFoundError:
            digest.update(b"<deleted>")
    return digest.hexdigest()


def assert_frozen(run):
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != run.context["frozen_head"] or source_fingerprint() != run.context["frozen_source"]:
        raise BlockedError("发布检查期间 HEAD 或受测内容已变化，本轮结果作废")


def docker_containers_running(names) -> dict:
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Status}}"],
                         capture_output=True, text=True)
    running = {}
    for line in out.stdout.splitlines():
        name, _, state = line.partition("\t")
        running[name] = state
    return {name: running.get(name) for name in names}


def require_stack(run: Run) -> dict:
    """本地栈三容器必须已起; 不替用户起栈(避免无声改变机器状态)。"""
    states = docker_containers_running(
        [API_CONTAINER, DB_CONTAINER, REDIS_CONTAINER])
    run.info("containers", states)
    missing = [name for name, state in states.items() if not state]
    if missing:
        raise BlockedError(
            "本地栈容器未运行: " + ", ".join(missing)
            + "; 先按 local/README.md 起栈(cd local/stack && docker compose "
              "--env-file .env.local up -d)")
    for container in (API_CONTAINER, DB_CONTAINER):
        inspected = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", container],
                                   capture_output=True, text=True, timeout=30)
        if inspected.returncode:
            raise BlockedError(f"不能检查 {container} 的源码挂载")
        sources = [m["Source"] for m in json.loads(inspected.stdout)
                   if m.get("Destination") == "/repo"]
        def host_path(value):
            for prefix in ("/host_mnt", "/run/desktop/mnt/host"):
                if value.startswith(prefix + "/"):
                    value = value[len(prefix):]
            return os.path.realpath(value)
        if len(sources) != 1 or host_path(sources[0]) != os.path.realpath(ROOT):
            raise BlockedError(f"{container} 的 /repo 不属于当前 checkout，拒绝错树验证")
    return states


# ─── backend: 每 run 专有库 + 容器内非 root 显式最小模块集 ───

def psql_as_app_user(run: Run, name, sql_args, *, cred, timeout=900):
    """db 容器内以应用账号执行 psql(密码经 docker -e 注入, 不入日志)。"""
    return run.docker(name, ["exec", "-e", "PGPASSWORD=" + cred["password"],
                             DB_CONTAINER, "psql", "-h", "127.0.0.1",
                             "-U", cred["user"], "-v", "ON_ERROR_STOP=1",
                             *sql_args], timeout=timeout)


def as_pg(run: Run, name, pg_cmd, *, timeout=180):
    """db 容器内以 postgres 管理身份执行(仅限建/删本 run 专有库)。"""
    return run.docker(name, ["exec", DB_CONTAINER, "su", "postgres",
                             "-s", "/bin/bash", "-c",
                             "/usr/lib/postgresql/16/bin/" + pg_cmd],
                      timeout=timeout)


def db_exists(run: Run, dbname: str) -> bool:
    code, _, out, _ = as_pg(
        run, "db-exists",
        f"psql -At -c \"SELECT 1 FROM pg_database WHERE datname='{dbname}'\"",
        timeout=60)
    return code == 0 and out.strip() == "1"


def create_run_db(run: Run, cred: dict, dbname: str) -> str:
    if db_exists(run, dbname):
        raise BlockedError(
            f"专有库 {dbname} 已存在但不是本 run 创建的; 拒绝动用, 换 run 重试")
    code, _, _, err = as_pg(run, "createdb", f"createdb -O {shlex.quote(cred['user'])} {dbname}")
    if code != 0:
        raise BlockedError("createdb 失败: " + err.strip()[:400])
    run.registry.append({"kind": "run_db", "ident": dbname})
    return dbname


def apply_baseline_and_migrations(run: Run, cred: dict, dbname: str):
    for sql in ("0000_baseline.sql", "0001_bootstrap_reference_data.sql"):
        code, _, _, err = psql_as_app_user(
            run, f"bootstrap-{sql[:4]}",
            ["-d", dbname, "-q", "-f", f"/repo/migrations/{sql}"],
            cred=cred, timeout=1200)
        if code != 0:
            raise BlockedError(f"{sql} 执行失败: " + err.strip()[:400])
    native = f"{NATIVE_SCHEME}{urllib.parse.quote(cred['user'], safe='')}:{urllib.parse.quote(cred['password'], safe='')}@db:5432/{dbname}"
    # 迁移 URL 必须是 psql 可用原生 scheme 且不带 sentinel(见 AGENTS)
    code, _, _, err = run.docker(
        "migrate-forward",
        ["exec", API_CONTAINER, VENV_PYTHON, "/repo/scripts/migrate.py", native],
        timeout=1200)
    if code != 0:
        raise BlockedError("forward 迁移失败: " + err.strip()[:400])


def verify_tester(run: Run):
    code, _, out, err = run.docker(
        "tester-uid", ["exec", "-u", TESTER_USER, API_CONTAINER, "id", "-u"], timeout=60)
    if code != 0 or not out.strip().isdigit() or int(out.strip()) == 0:
        raise BlockedError(
            f"容器内缺少非 root 用户 {TESTER_USER}: 镜像过旧, 需重建"
            "(cd local/stack && docker compose --env-file .env.local "
            "up -d --build api)")
    run.info("tester_uid", out.strip())


def validate_modules(modules):
    if not modules:
        raise UsageError("backend 需要显式模块列表(--tests tests.xxx ...); "
                         "空选择不得执行, 也不 fallback 全量 discover")
    bad = [m for m in modules if not TEST_MODULE_RE.match(m)]
    if bad:
        raise UsageError("模块名必须是 tests.<name> 形状, 收到: " + ", ".join(bad))


class RedisLock:
    """主机侧文件锁: 本地测试 Redis 只有一个逻辑库(DB15), run 间串行。"""

    def __init__(self):
        os.makedirs(os.path.dirname(REDIS_LOCK_FILE), exist_ok=True)
        self.handle = None

    def acquire(self):
        self.handle = open(REDIS_LOCK_FILE, "a+")
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    self.handle = None
                    raise BlockedError("Redis DB15 被其他 run 占用，等待30s超时")
                time.sleep(0.1)
        if os.path.exists(REDIS_LOCK_FILE + ".unsafe"):
            self.release()
            raise BlockedError("上轮远程进程停止未确认；先核实隔离标记再使用 Redis DB15")
        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(f"{os.getpid()} {now_iso()}\n")
        self.handle.flush()

    def release(self):
        if self.handle is not None:
            try:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            finally:
                self.handle.close()
                self.handle = None


def docker_test_env(test_url, app_url, run_id):
    return ["-u", TESTER_USER,
            "-e", f"TEST_DATABASE_URL={test_url}",
            "-e", f"HGS_DATABASE_URL={app_url}",
            "-e", f"HGS_REDIS_URL={TEST_REDIS_URL}",
            "-e", f"HGS_SKILL_ROOT=/tmp/{run_id}/skills",
            "-e", f"HGS_AVATAR_ROOT=/tmp/{run_id}/avatars",
            "-e", f"HGS_PUBLIC_BASE_URL={CANONICAL_BASE_URL}",
            "-e", f"HOME=/home/{TESTER_USER}"]


def prepare_container_dirs(run: Run, run_id):
    code, _, _, err = run.docker(
        "tmpdirs", ["exec", "-u", TESTER_USER, API_CONTAINER, "mkdir", "-p",
                    f"/tmp/{run_id}/skills", f"/tmp/{run_id}/avatars"],
        timeout=60)
    if code != 0:
        raise BlockedError("run 专有目录创建失败: " + err.strip()[:300])
    run.registry.append({"kind": "container_tmpdir", "ident": f"/tmp/{run_id}"})


def check_modules_importable(run: Run, modules, env_args):
    """模块必须可导入 — 丢失模块在跑测试之前就失败, 不进入半跑状态。"""
    code, _, _, err = run.docker(
        "module-import-check",
        ["exec", "-w", "/repo", *env_args, API_CONTAINER, VENV_PYTHON, "-c",
         "import importlib, sys\n"
         "for name in sys.argv[1:]:\n"
         "    importlib.import_module(name)\n", *modules],
        timeout=300)
    if code != 0:
        raise BlockedError(
            "模块导入失败(模块缺失或 import 期错误): " + err.strip()[:400])


def resolve_cleanup(kind, ident):
    """把登记资源解析为清理动作; 未知类型或越形状标识一律拒绝返回 None。

    run_db 的目标名必须匹配 run 专有库模式 — 通配或异形状标识到不了
    dropdb 的 shell 命令串里。
    """
    if kind == "run_db":
        if not RUN_DB_NAME_RE.match(str(ident)):
            return None
        return ("as_pg", f"dropdb --if-exists {ident}")
    if kind == "container_tmpdir" and str(ident).startswith("/tmp/"):
        return ("docker_rm", str(ident))
    return None


def real_cleanup_executor(run: Run):
    def execute(kind, ident):
        action = resolve_cleanup(kind, ident)
        if action is None:
            return False, f"拒绝清理: 未登记形状的资源 {kind} {ident}"
        if action[0] == "as_pg":
            code, _, _, err = as_pg(run, "dropdb", action[1])
            return code == 0, (None if code == 0 else err.strip()[:300])
        code, _, _, err = run.docker(
            "rmtree", ["exec", API_CONTAINER, "rm", "-rf", action[1]],
            timeout=180)
        return code == 0, (None if code == 0 else err.strip()[:300])
    return execute


def do_cleanup(run: Run):
    if not run.processes_stopped:
        run.cleanup_results = [{"kind": r["kind"], "ident": r["ident"],
                                "cleaned": False, "error": "进程停止未确认"} for r in run.registry]
        return
    results = cleanup_resources(run.registry, real_cleanup_executor(run))
    run.cleanup_results = results
    leftover = [r for r in results if not r["cleaned"]]
    if leftover:
        print("[check.py] 清理失败残留(需人工处理): "
              + json.dumps(safe_value(leftover), ensure_ascii=False))


def cmd_backend(args) -> int:
    validate_modules(args.tests)
    run = Run("backend")
    git_snapshot(run)
    run.info("invoked_cwd", globals().get("_INVOKED_CWD", os.getcwd()))
    run.info("modules", args.tests)
    run.info("test_redis", TEST_REDIS_URL)
    lock = RedisLock()
    held = False
    outcome = ("BLOCKED", "未执行")
    try:
        stack_env = load_stack_env()
        cred = {"user": stack_env["HGS_DB_USER"],
                "password": stack_env["HGS_DB_PASSWORD"]}
        require_stack(run)
        verify_tester(run)
        _, _, out, _ = run.docker(
            "venv-python-version",
            ["exec", API_CONTAINER, VENV_PYTHON, "--version"], timeout=60)
        run.info("backend_python", out.strip())
        dbname = run_db_name()
        test_url, app_url, _ = build_test_urls(
            cred["user"], cred["password"], "db", 5432, dbname)
        create_run_db(run, cred, dbname)
        apply_baseline_and_migrations(run, cred, dbname)
        run.info("test_db", {"host": "db", "port": 5432, "database": dbname,
                             "user": cred["user"]})
        prepare_container_dirs(run, run.run_id)
        env_args = docker_test_env(test_url, app_url, run.run_id)
        lock.acquire()
        held = True
        check_modules_importable(run, args.tests, env_args)
        code, timed_out, _, stderr = run.exec(
            "unittest",
            ["docker", "exec", *env_args, API_CONTAINER, "bash", "-lc",
             "cd /repo && exec " + VENV_PYTHON + " -m unittest -v "
             + " ".join(args.tests)],
            timeout=args.timeout)
        if timed_out:
            raise BlockedError(f"unittest 超过 {args.timeout}s 被终止")
        if code != 0:
            raise FailError(f"unittest 子进程退出 {code}")
        parsed = parse_unittest_output(stderr)
        run.info("unittest_summary", parsed)
        v = verdict(parsed, args.allow_skip, args.allow_xfail)
        if v["status"] != "PASS":
            raise FailError(v["reason"] or "unittest 失败")
        outcome = ("PASS", f"ran={parsed['ran']} "
                   f"skips={parsed['counts']['skipped']} " + (v["reason"] or ""))
    except (BlockedError, EnvTargetMismatch) as exc:
        outcome = ("BLOCKED", str(exc))
    except FailError as exc:
        outcome = ("FAIL", str(exc))
    finally:
        if held:
            lock.release()
        do_cleanup(run)
    return run.finish(*outcome)


# ─── web: 宿主 Node 四件套(默认不 build) ───

NODE_MIN_MAJOR = 22
WEB_STEPS = (("tsc", ["npx", "tsc", "--noEmit"]),
             ("test:unit", ["npm", "run", "test:unit"]),
             ("test:locale", ["npm", "run", "test:locale"]),
             ("check:api-layer", ["npm", "run", "check:api-layer"]))


def host_node_version():
    try:
        out = subprocess.run(["node", "-p", "process.versions.node"],
                             capture_output=True, text=True, timeout=30)
        version = out.stdout.strip()
        return (int(version.split(".")[0]) if version else 0), version
    except (OSError, ValueError):
        return 0, ""


def run_web_steps(run: Run, timeout: int):
    major, version = host_node_version()
    run.info("node", version)
    capability = subprocess.run(["node", "--experimental-strip-types", "-e", ""],
                                capture_output=True, timeout=30) if major >= NODE_MIN_MAJOR else None
    if major < NODE_MIN_MAJOR or capability.returncode != 0:
        raise BlockedError(
            f"宿主 Node {version or '缺失'} 低于基准 {NODE_MIN_MAJOR} 系列")
    if not os.path.isdir(os.path.join(ROOT, "web", "node_modules")):
        raise BlockedError("web/node_modules 缺失: 先在 web/ 执行 npm ci")
    for name, cmd in WEB_STEPS:
        code, timed_out, _, _ = run.exec(name, cmd,
                                         cwd=os.path.join(ROOT, "web"),
                                         timeout=timeout)
        if timed_out or code != 0:
            raise FailError(f"web 检查在 {name} 步失败(日志 {run.dir})")


def cmd_web(args) -> int:
    run = Run("web")
    git_snapshot(run)
    run.info("invoked_cwd", globals().get("_INVOKED_CWD", os.getcwd()))
    try:
        run_web_steps(run, args.timeout)
        return run.finish("PASS", "tsc/test:unit/test:locale/check:api-layer 全过")
    except BlockedError as exc:
        return run.finish("BLOCKED", str(exc))
    except FailError as exc:
        return run.finish("FAIL", str(exc))


# ─── worker: 一次性干净 venv 只装 requirements-worker.txt ───

def run_worker_steps(worker_run: Run, install_timeout: int, timeout: int):
    require_stack(worker_run)
    verify_tester(worker_run)
    worker_run.info("worker_python", tool_version(["docker", "exec", API_CONTAINER, "python3", "--version"]))
    venv = f"/tmp/{worker_run.run_id}/wvenv"
    worker_run.registry.append(
        {"kind": "container_tmpdir", "ident": f"/tmp/{worker_run.run_id}"})
    home = ["-e", f"HOME=/home/{TESTER_USER}"]
    # pip 轮子缓存放容器内持久目录(tester 家): 「干净 venv + 只装
    # requirements-worker」的验证语义不变, 但免得每次门禁全量重下大轮子。
    pip_cache = f"/home/{TESTER_USER}/.cache/pip"
    code, _, _, err = worker_run.docker(
        "mkdir", ["exec", "-u", TESTER_USER, API_CONTAINER, "mkdir", "-p",
                  pip_cache], timeout=60)
    if code != 0:
        raise BlockedError("pip 缓存目录创建失败: " + err.strip()[:300])
    code, _, _, err = worker_run.docker(
        "venv-create", ["exec", "-u", TESTER_USER, *home, API_CONTAINER,
                        "python3", "-m", "venv", venv], timeout=300)
    if code != 0:
        raise BlockedError("干净 venv 创建失败: " + err.strip()[:300])
    # 隔离自证: 干净 venv 不得解析应用 venv 的 site-packages
    code, _, out, err = worker_run.docker(
        "venv-isolation",
        ["exec", "-u", TESTER_USER, API_CONTAINER, venv + "/bin/python",
         "-c", "import sys, json; print(json.dumps(sys.path))"], timeout=60)
    if code != 0 or "/opt/venv" in out:
        raise BlockedError("干净 venv 未隔离(可见应用 site-packages 或探测失败): "
                           + out.strip()[:200] + err.strip()[:200])
    # 宿主 PIP_INDEX_URL 透传(容器到官方源的链路慢时可注入镜像);
    # 未设即 pip 默认官方源, 仓库不指定任何镜像。
    index_env = (["-e", "PIP_INDEX_URL=" + os.environ["PIP_INDEX_URL"]]
                 if os.environ.get("PIP_INDEX_URL") else [])
    code, timed_out, _, stderr = worker_run.exec(
        "pip-install-worker-reqs",
        ["docker", "exec", "-u", TESTER_USER, *home, *index_env,
         "-e", f"PIP_CACHE_DIR={pip_cache}",
         API_CONTAINER, "bash", "-c",
         f"{venv}/bin/pip install --disable-pip-version-check --retries 2 "
         f"--timeout 60 -r /repo/requirements-worker.txt"],
        timeout=install_timeout)
    if timed_out:
        raise BlockedError(
            f"worker 依赖安装超过 {install_timeout}s; 如实记 BLOCKED, "
            "不用应用 venv 冒充干净环境")
    if code != 0:
        raise FailError("requirements-worker.txt 安装失败(网络/包可用性): "
                        + stderr.strip()[:300])
    code, timed_out, _, _ = worker_run.exec(
        "worker-import-check",
        ["docker", "exec", "-u", TESTER_USER, *home, API_CONTAINER,
         venv + "/bin/python", "/repo/scripts/check_worker_imports.py"],
        timeout=timeout)
    if timed_out:
        raise BlockedError("worker 导入检查超时")
    if code != 0:
        raise FailError("worker 干净环境导入失败")


def cmd_worker(args) -> int:
    run = Run("worker")
    git_snapshot(run)
    run.info("invoked_cwd", globals().get("_INVOKED_CWD", os.getcwd()))
    outcome = ("BLOCKED", "未执行")
    try:
        run_worker_steps(run, args.install_timeout, args.timeout)
        outcome = ("PASS", "requirements-worker.txt 干净 venv 导入检查通过")
    except BlockedError as exc:
        outcome = ("BLOCKED", str(exc))
    except FailError as exc:
        outcome = ("FAIL", str(exc))
    finally:
        do_cleanup(run)
    return run.finish(*outcome)


# ─── preflight: 只读盘点 ───

LOCAL_PORTS = {3000: "next dev", 3010: "uploads 静态", 8000: "api",
               55433: "postgres", 56380: "redis"}


def port_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def tool_version(argv):
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        return (out.stdout + out.stderr).strip().splitlines()[0]
    except (OSError, IndexError, subprocess.TimeoutExpired):
        return "缺失"


def cmd_preflight(args) -> int:
    run = Run("preflight")
    git_snapshot(run)
    run.info("invoked_cwd", globals().get("_INVOKED_CWD", os.getcwd()))
    run.info("repo_root", ROOT)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                            cwd=ROOT, capture_output=True, text=True)
    run.info("branch", branch.stdout.strip())
    run.info("python3_host", tool_version(["python3", "--version"]))
    major, version = host_node_version()
    run.info("node", version or "缺失")
    run.info("node_meets_baseline", bool(major >= NODE_MIN_MAJOR))
    run.info("npm", tool_version(["npm", "--version"]))
    run.info("containers", docker_containers_running(
        [API_CONTAINER, DB_CONTAINER, REDIS_CONTAINER]))
    uid = subprocess.run(["docker", "exec", API_CONTAINER, "id", TESTER_USER],
                         capture_output=True, text=True)
    run.info("tester_uid", uid.stdout.strip() or f"缺失(exit {uid.returncode})")
    run.info("backend_python", tool_version(
        ["docker", "exec", API_CONTAINER, VENV_PYTHON, "--version"]))
    run.info("stack_env_file", os.path.exists(STACK_ENV_FILE))
    run.info("ports", {str(port): (port_listening(port), label)
                       for port, label in LOCAL_PORTS.items()})
    action, message = dev_build_decision(DEV_MARKER, BUILD_MARKER)
    run.info("dev_build_mutex", {"action": action, "message": message})
    writable = False
    try:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "probe"), "w") as fh:
                fh.write("ok")
            writable = True
    except OSError:
        writable = False
    run.info("host_tmp_writable", writable)
    run.info("runs_dir", {"path": RUNS_DIR, "exists": os.path.isdir(RUNS_DIR)})
    for key in sorted(run.context):
        print(f"  {key}: {json.dumps(run.context[key], ensure_ascii=False)}")
    print("[check.py] preflight 只读盘点, 不判 pass/fail, 未写库/未杀进程/未装包")
    with open(os.path.join(run.dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump({"run_id": run.run_id, "command": "preflight",
                   "started": run.started, "finished": now_iso(),
                   "environment": run.context, "steps": run.steps,
                   "cleanup": [], "overall": "INFO"},
                  fh, ensure_ascii=False, indent=2)
    return EXIT_PASS


# ─── release: 显式发布门禁 ───

RELEASE_PHASES = ["freeze", "mutex-guard", "fresh-db", "backend-full",
                  "web", "build", "worker"]


def release_dev_guard(run: Run):
    """build 前的 dev 在跑判定: 标记或端口证据任一命中即拒绝。

    旧方式启动的 dev 没有标记, 端口 3000 是保守的兜底证据; 误伤其他
    占端口进程时由操作者腾出端口或改用隔离 checkout, 绝不猎杀进程。
    """
    action, message = dev_build_decision(DEV_MARKER, BUILD_MARKER)
    if action in ("dev_active", "build_active"):
        raise BlockedError(message)
    if port_listening(3000):
        raise BlockedError(
            "端口 3000 有监听(疑似 next dev 在跑, 含旧标记机制前启动的"
            "实例): production build 会覆盖 dev 产物。先停 local/dev.sh,"
            "或确认非本 checkout 的 dev 并腾出端口, 或改用隔离 checkout。")
    run.info("dev_guard", "标记与端口均无 dev 迹象")


def cmd_release(args) -> int:
    run = Run("release")
    head, status = git_snapshot(run)
    run.info("invoked_cwd", globals().get("_INVOKED_CWD", os.getcwd()))
    run.info("phases", RELEASE_PHASES)
    if args.dry_run:
        plan = {"phases": RELEASE_PHASES,
                "head": head,
                "dirty_count": len(status or []),
                "backend_full": "专有库 baseline+bootstrap+forward 后全量 discover",
                "build": "npm run build(要求无运行中 dev)",
                "worker": "干净 venv 只装 requirements-worker.txt"}
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        with open(os.path.join(run.dir, "plan.json"), "w", encoding="utf-8") as fh:
            json.dump(plan, fh, ensure_ascii=False, indent=2)
        print("[check.py] dry-run 只列计划: 未执行检查、未触任何库、未装包")
        return EXIT_PASS
    run.info("frozen_head", head)
    run.info("frozen_source", source_fingerprint())
    if status:
        print(f"[check.py] 工作树有 {len(status)} 个未提交改动: 本次结果只作为"
              " working-tree 证据, 不冒充已提交 SHA 的发行证据")
    lock = RedisLock()
    held = False
    build_marker_on = False
    outcome = ("BLOCKED", "未执行")
    try:
        # mutex-guard: build 不得覆盖运行中 dev 的产物
        release_dev_guard(run)
        # fresh-db + backend-full: 全量也在 run 专有库与非 root 下执行
        stack_env = load_stack_env()
        cred = {"user": stack_env["HGS_DB_USER"],
                "password": stack_env["HGS_DB_PASSWORD"]}
        require_stack(run)
        verify_tester(run)
        dbname = run_db_name()
        test_url, app_url, _ = build_test_urls(
            cred["user"], cred["password"], "db", 5432, dbname)
        create_run_db(run, cred, dbname)
        apply_baseline_and_migrations(run, cred, dbname)
        run.info("test_db", {"host": "db", "port": 5432, "database": dbname,
                             "user": cred["user"]})
        run.info("test_redis", TEST_REDIS_URL)
        prepare_container_dirs(run, run.run_id)
        env_args = docker_test_env(test_url, app_url, run.run_id)
        lock.acquire()
        held = True
        code, timed_out, _, stderr = run.exec(
            "unittest-discover",
            ["docker", "exec", *env_args, API_CONTAINER, "bash", "-lc",
             "cd /repo && exec " + VENV_PYTHON
             + " -m unittest discover -s tests -t . -v"],
            timeout=args.backend_timeout)
        if timed_out:
            raise BlockedError(f"全量后端超时({args.backend_timeout}s)")
        if code != 0:
            raise FailError(f"unittest 子进程退出 {code}")
        parsed = parse_unittest_output(stderr)
        run.info("unittest_summary", parsed)
        v = verdict(parsed, args.allow_skip, args.allow_xfail)
        if v["status"] != "PASS":
            raise FailError("backend-full: " + (v["reason"] or "")
                            + "; 明细 " + json.dumps(v.get("details", []),
                                                     ensure_ascii=False))
        lock.release()
        held = False
        # web + build + worker
        assert_frozen(run)
        run_web_steps(run, 900)
        try:
            with next_lock.OutputLock():
                assert_frozen(run)
                release_dev_guard(run)
                write_marker(BUILD_MARKER, "build")
                build_marker_on = True
                try:
                    code, timed_out, _, _ = run.exec(
                        "next-build", ["npm", "run", "build"],
                        cwd=os.path.join(ROOT, "web"), timeout=args.build_timeout)
                    if timed_out or code != 0:
                        raise FailError("production build 失败")
                finally:
                    remove_marker(BUILD_MARKER)
                    build_marker_on = False
        except RuntimeError as exc:
            if isinstance(exc, (BlockedError, FailError)):
                raise
            raise BlockedError(str(exc)) from exc
        worker_run = Run("release-worker")
        run.info("worker_run_id", worker_run.run_id)
        worker_outcome = ("BLOCKED", "未执行")
        try:
            run_worker_steps(worker_run, args.worker_install_timeout,
                             args.worker_timeout)
            worker_outcome = ("PASS", "worker 干净 venv 通过")
        except BlockedError as exc:
            worker_outcome = ("BLOCKED", str(exc))
        except FailError as exc:
            worker_outcome = ("FAIL", str(exc))
        finally:
            do_cleanup(worker_run)
        worker_run.finish(*worker_outcome)
        if worker_outcome[0] != "PASS":
            raise (BlockedError if worker_outcome[0] == "BLOCKED" else FailError)(
                "worker 阶段未通过: " + worker_outcome[1])
        assert_frozen(run)
        outcome = ("PASS", "发布门禁全阶段完成(证据见 run 目录)")
    except (BlockedError, EnvTargetMismatch) as exc:
        outcome = ("BLOCKED", str(exc))
    except FailError as exc:
        outcome = ("FAIL", str(exc))
    finally:
        if held:
            lock.release()
        if build_marker_on:
            remove_marker(BUILD_MARKER)
        do_cleanup(run)
    return run.finish(*outcome)


# ─── CLI ───

def positive_timeout(raw):
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("timeout 必须大于0")
    return value


class Parser(argparse.ArgumentParser):
    def error(self, message):  # 用法错误统一退出码 3
        self.print_usage(sys.stderr)
        print(f"check.py: 用法错误: {message}", file=sys.stderr)
        sys.exit(EXIT_USAGE)


def build_parser() -> Parser:
    ap = Parser(prog="python3 local/check.py",
                description="HGS 仓库检查编排器(手册: docs/TESTING.md)")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("preflight", help="只读环境盘点")\
        .set_defaults(func=cmd_preflight)

    web = sub.add_parser("web", help="前端检查(默认不 build)")
    web.add_argument("--timeout", type=positive_timeout, default=900)
    web.set_defaults(func=cmd_web)

    backend = sub.add_parser("backend", help="容器内非 root 后端最小模块集")
    backend.add_argument("--tests", nargs="+", required=True,
                         metavar="tests.<module>",
                         help="显式模块列表; 空选择/未知模块非零退出, 不 fallback 全量")
    backend.add_argument("--timeout", type=positive_timeout, default=1800)
    backend.add_argument("--allow-skip", nargs="*", default=[], metavar="CASE",
                         help="许可的用例级 skip(完整 id 逐项列出); 不接受整模块白名单")
    backend.add_argument("--allow-xfail", nargs="*", default=[], metavar="CASE")
    backend.set_defaults(func=cmd_backend)

    worker = sub.add_parser("worker", help="干净 venv worker 导入检查")
    worker.add_argument("--install-timeout", type=positive_timeout, default=900)
    worker.add_argument("--timeout", type=positive_timeout, default=300)
    worker.set_defaults(func=cmd_worker)

    release = sub.add_parser("release", help="显式发布门禁")
    release.add_argument("--dry-run", action="store_true", help="只列计划, 不执行")
    release.add_argument("--backend-timeout", type=positive_timeout, default=3600)
    release.add_argument("--build-timeout", type=positive_timeout, default=1800)
    release.add_argument("--worker-install-timeout", type=positive_timeout, default=900)
    release.add_argument("--worker-timeout", type=positive_timeout, default=300)
    release.add_argument("--allow-skip", nargs="*", default=[], metavar="CASE")
    release.add_argument("--allow-xfail", nargs="*", default=[], metavar="CASE")
    release.set_defaults(func=cmd_release)
    return ap


def interrupt_check(*_):
    raise KeyboardInterrupt()


def main(argv=None) -> int:
    signal.signal(signal.SIGTERM, interrupt_check)
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    invoked_cwd = os.getcwd()
    # cwd 纪律: 本仓库树内任意位置自动回根并记录; 在别的树上直接拒绝
    try:
        inside = os.path.commonpath([invoked_cwd, ROOT]) == ROOT
    except ValueError:
        inside = False
    if not inside:
        print(f"check.py: 拒绝执行 — cwd {invoked_cwd} 不在仓库 {ROOT} 内, "
              "不得静默跑另一套树", file=sys.stderr)
        return EXIT_USAGE
    global _INVOKED_CWD
    _INVOKED_CWD = invoked_cwd
    if invoked_cwd != ROOT:
        print(f"[check.py] 从 {invoked_cwd} 调用, 切回仓库根 {ROOT}")
        os.chdir(ROOT)
    try:
        return args.func(args)
    except UsageError as exc:
        print(redact(f"check.py: {exc}"), file=sys.stderr)
        return EXIT_USAGE
    except (OSError, BlockedError) as exc:
        if _ACTIVE_RUN:
            return _ACTIVE_RUN.finish("BLOCKED", str(exc))
        print(redact(str(exc)), file=sys.stderr)
        return EXIT_BLOCKED
    except Exception:
        detail = redact(traceback.format_exc())
        if _ACTIVE_RUN:
            return _ACTIVE_RUN.finish("FAIL", detail)
        print(detail, file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
