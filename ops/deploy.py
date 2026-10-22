"""单实例部署 owner。

职责(仅此而已):
  1. fail-closed 检查执行用户不是 root(mutating deploy 禁 root)
  2. build Web(单一 canonical `.next`)
  3. 使用仓库根 `ecosystem.config.cjs`(canonical, 不生成任何 spec)
  4. restart/start API 与 Web → 等 API/Web health 就绪 → **就绪后**才
     restart/start worker(worker 启动 preflight 鉴权
     /workapi/v1/jobs/lease 依赖 API; API 未就绪时 worker 会 exit 1
     crash-loop)
  5. readiness: worker online 稳定窗 + public smoke + `pm2 save`

不承诺 zero-downtime: restart 存在短暂维护窗口(已接受)。
nginx 拓扑不在本 owner 职责内(生产为固定 upstream 8000/3001, 不随发布重写);
bootstrap 子命令提供一次性 nginx canonical 化(install/validate/reload), 日常发布不动 nginx。
禁止重新引入 blue/green/generation/active symlink/临时端口机制。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent

CANONICAL_APPS = (
    "huagongshe-api",       # API 127.0.0.1:8000
    "huagongshe",           # Web 127.0.0.1:3001
    "huagongshe-pubchem-worker",  # worker, HGS_WORKER_ID=server-local-1
)
# 部署顺序: 先重启前置的 API/Web, 等 API health 就绪后才重启 worker ——
# worker 启动 preflight 鉴权(/workapi/v1/jobs/lease)连不上 API 就 exit 1,
# 提前重启只会 crash-loop 到 API 就绪。
FRONTING_APPS = CANONICAL_APPS[:2]
WORKER_APP = CANONICAL_APPS[2]
API_PORT = 8000
WEB_PORT = 3001
API_HEALTH = f"http://127.0.0.1:{API_PORT}/api/health"
WEB_HEALTH = f"http://127.0.0.1:{WEB_PORT}/api/health"
# canonical public ingress smoke: 走真实公网 vhost(nginx + TLS + canonical host + API upstream),
# 不再重复裸 loopback readiness(8000/3001 已在 readiness 阶段覆盖; 裸 IP 无 Host 会被
# 00-default-444 default_server 444 断连)。
# 专用 probe UA: Cloudflare 对 urllib 默认 Python-urllib/3.x UA 返回 403(bot 规则);
# UA 表达真实身份(化工社部署 smoke probe), 非浏览器伪装, 不加 CF 专属 cookie/header。
PUBLIC_SMOKE_URL = "https://huagongshe.com/api/health"
PUBLIC_SMOKE_HEADERS = {
    "User-Agent": "Huagongshe-Deploy-Smoke/1.0",
}
SPEC = REPO / "ecosystem.config.cjs"

# nginx canonical(一次性 bootstrap 用; 日常发布不触碰)
NGINX_SITE = Path("/etc/nginx/sites-enabled/huagongshe")
NGINX_HGS_ROOT = Path("/etc/nginx/hgs")
NGINX_CANONICAL_UPSTREAMS = (
    ("hgs_api", f"127.0.0.1:{API_PORT}"),
    ("hgs_web", f"127.0.0.1:{WEB_PORT}"),
)


class DeployError(RuntimeError):
    pass


def _event(name: str, **kw) -> None:
    print(f"[{name}]" + (f" {json.dumps(kw, ensure_ascii=False)}" if kw else ""),
          flush=True)


CHILD_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def child_env() -> dict[str, str]:
    """子进程只拿最小环境, 不继承调用方终端。

    pm2 start/restart --update-env 会把调用方环境整体写进 app 进程与
    dump.pm2; app 所需变量一律来自 ecosystem.config.cjs 与 /etc/huagongshe.env。
    """
    env = {"PATH": CHILD_PATH, "LANG": "C.UTF-8"}
    for key in ("HOME", "USER", "LOGNAME", "PM2_HOME"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


@dataclass
class Runner:
    """subprocess 执行器; 测试注入 FakeRunner 替代。"""

    run: Callable[[list[str]], "subprocess.CompletedProcess"]

    @classmethod
    def real(cls) -> "Runner":
        def _run(argv: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(argv, capture_output=True, text=True,
                                  env=child_env())
        return cls(run=_run)


# ---------------------------------------------------------------- guards --

def require_non_root() -> None:
    """mutating deploy 禁 root: root 会把 app 落进 root PM2 daemon, 与运行账号的 daemon 分裂。"""
    if os.geteuid() == 0:
        raise DeployError(
            "不要使用: sudo python -m ops.deploy —— 部署脚本由 deployment user 执行; "
            "只有必要的 nginx/system 操作单独 sudo"
        )


# ------------------------------------------------------------------ nginx --

def nginx_bootstrap(runner: Runner, apply: bool = True) -> bool:
    """一次性把 site config 恢复为固定 upstream 8000/3001(幂等)。

    日常发布不调用; 只用于从 generation 拓扑迁回 canonical。
    """
    require_non_root()
    if not NGINX_SITE.exists():
        raise DeployError(f"nginx site 不存在: {NGINX_SITE}; 先人工安装")
    text = NGINX_SITE.read_text()
    changed = False
    # generation include → 固定 upstream(如仍存在)
    gen_include = f"include {NGINX_HGS_ROOT}/generations/active.conf;"
    if gen_include in text:
        text = text.replace(gen_include, _canonical_upstream_block())
        changed = True
    # hgs_api_active/hgs_web_active 名称 → 固定名
    for old, new in (("hgs_api_active", "hgs_api"), ("hgs_web_active", "hgs_web")):
        if old in text:
            text = text.replace(old, new)
            changed = True
    if changed:
        if not apply:
            _event("nginx.canonical.dryrun", changed=True)
            return False
        backup = NGINX_HGS_ROOT / f"huagongshe.pre-single-{int(time.time())}.bak"
        runner.run(["sudo", "-n", "cp", str(NGINX_SITE), str(backup)])
        tmp = Path("/tmp") / f"hgs-site-{int(time.time())}.conf"
        tmp.write_text(text)
        r = runner.run(["sudo", "-n", "cp", str(tmp), str(NGINX_SITE)])
        tmp.unlink(missing_ok=True)
        if r.returncode != 0:
            raise DeployError(f"site config 写回失败: exit={r.returncode}")
    # 校验 + reload(单独 sudo, 非 root 运行)
    t = runner.run(["sudo", "-n", "nginx", "-t"])
    if t.returncode != 0:
        raise DeployError(f"nginx -t 失败: {t.stderr.strip()[:300]}")
    if changed:
        r = runner.run(["sudo", "-n", "nginx", "-s", "reload"])
        if r.returncode != 0:
            raise DeployError(f"nginx reload 失败: {r.stderr.strip()[:300]}")
    _event("nginx.canonical.ok", changed=changed)
    return True


def _canonical_upstream_block() -> str:
    return (
        "upstream hgs_api { server 127.0.0.1:8000; }\n"
        "upstream hgs_web { server 127.0.0.1:3001; }\n"
    )


# ------------------------------------------------------------------ pm2 ----

def pm2_argv(runner_homeless: bool = False) -> str:
    return "pm2"


def start_canonical(runner: Runner, app: str) -> None:
    """canonical app 不存在 → start 整 spec 不行(会带起全部); 单 app 增量启动。"""
    jlist = runner.run([pm2_argv(), "jlist"])
    if jlist.returncode != 0:
        raise DeployError(f"pm2 jlist 失败: exit={jlist.returncode}")
    existing = {a["name"] for a in _parse_jlist(jlist.stdout)}
    if app not in existing:
        r = runner.run([pm2_argv(), "start", str(SPEC), "--only", app])
        if r.returncode != 0:
            raise DeployError(f"pm2 start --only {app} 失败: exit={r.returncode}")
        _event("pm2.started", app=app)
    else:
        # 已存在应用的重启必须带 ecosystem 路径 —
        # 裸 `restart APP --update-env` 只刷新运行时 env, 不重读 spec,
        # 改配置/轮换 Token 后新值可能不生效且部署仍报成功。
        r = runner.run([pm2_argv(), "restart", str(SPEC), "--only", app,
                        "--update-env"])
        if r.returncode != 0:
            raise DeployError(f"pm2 restart {app} 失败: exit={r.returncode}")
        _event("pm2.restarted", app=app)


def _parse_jlist(stdout: str) -> list[dict]:
    try:
        return json.loads(stdout or "[]")
    except json.JSONDecodeError as e:
        raise DeployError(f"pm2 jlist 输出不可解析: {e}") from e


def worker_online(runner: Runner, app: str = "huagongshe-pubchem-worker") -> bool:
    jlist = runner.run([pm2_argv(), "jlist"])
    if jlist.returncode != 0:
        return False
    for a in _parse_jlist(jlist.stdout):
        if a.get("name") == app:
            return a.get("pm2_env", {}).get("status") == "online"
    return False


def _worker_identity(jlist_entry: dict) -> tuple | None:
    """(pm_id, pid) — 用于稳定性判定。

    标准 pm2 jlist 的 pid 在条目顶层, pm2_env 内
    无此键 —— 旧实现读 pm2_env.pid 恒 None, restart 循环(同 pm_id、顶层
    pid 每次变)被误判为同一稳定进程。"""
    env = jlist_entry.get("pm2_env", {})
    return env.get("pm_id"), jlist_entry.get("pid")


def wait_worker_online(runner: Runner, timeout: float = 60.0,
                       poll: float = 2.0, stable_seconds: float = 3.0) -> bool:
    """R4.1 1.4: worker 不但要 online, 还要稳定。

    同一 PM2 进程(pid 不变)连续 online 满一个短窗口(默认 3s)才算 ready —
    startup auth preflight 的 crash/restart 循环不能被误判 ready。
    pid 变化 / restart / missing / errored → 重新计时。
    """
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    last_identity: tuple | None = None
    while time.monotonic() < deadline:
        jlist = runner.run([pm2_argv(), "jlist"])
        entry = None
        if jlist.returncode == 0:
            for a in _parse_jlist(jlist.stdout):
                if a.get("name") == "huagongshe-pubchem-worker":
                    entry = a
                    break
        ok = (
            entry is not None
            and entry.get("pm2_env", {}).get("status") == "online"
            and entry.get("pid")
        )
        ident = _worker_identity(entry) if entry else None
        if ok and ident is not None and ident == last_identity and stable_since is not None:
            if time.monotonic() - stable_since >= stable_seconds:
                return True
        elif ok and (stable_since is None or ident != last_identity):
            # 首次 online 或进程身份变化 → 重新起算稳定窗
            stable_since = time.monotonic()
            last_identity = ident
        else:
            stable_since = None
            last_identity = None
        time.sleep(poll)
    return False


# -------------------------------------------------------------- readiness --

def http_ok(url: str, timeout: float = 5.0,
            headers: dict[str, str] | None = None) -> tuple[bool, str]:
    try:
        import urllib.request
        if headers is not None:
            # 显式 headers(如 canonical public smoke 的专用 probe UA):
            # 走 Request 构造; TLS 仍用 urllib 默认校验, timeout 语义不变。
            req = urllib.request.Request(url, headers=headers)
        else:
            req = url  # 现有 loopback readiness 行为保持不变
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(256).decode("utf-8", "replace")[:]
            return resp.status == 200 and '"status":"ok"' in body.replace(" ", ""), \
                   f"status={resp.status}"
    except Exception as e:  # noqa: BLE001
        return False, repr(e)[:200]


def wait_http_ok(url: str, timeout: float = 90.0, poll: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ok, _ = http_ok(url)
        if ok:
            return True
        time.sleep(poll)
    return False


# ------------------------------------------------------------- smoke -------

SMOKE_LOCALES = ("zh-CN", "en", "ja", "ko", "de")
SMOKE_CHEMICAL_PAGE = "https://huagongshe.com/en/chemical/4"  # HCID 4 详情页
SMOKE_MCP_URL = "https://huagongshe.com/mcp"


def _http_post_json(url: str, payload: dict, headers: dict[str, str],
                    timeout: float = 10.0) -> tuple[int, str]:
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(4096).decode("utf-8", "replace")


def _http_200(url: str, headers: dict[str, str], timeout: float = 10.0) -> tuple[bool, str]:
    """页面冒烟: 只看 200(HTML 页无 status:ok 契约; 不跟随 3xx)。"""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200, f"status={resp.status}"
    except Exception as e:  # noqa: BLE001 — 冒烟 fail closed, 不抛出
        return False, f"error={e}"


def public_smoke() -> bool:
    """canonical HTTPS 公网冒烟(扩充), 任一项失败 → deploy 非零退出。

    经公网 canonical ingress(https://huagongshe.com)验证:
    1. /api/health 200 + status=ok(nginx → TLS → API 127.0.0.1:8000 整链);
    2. 五种语言首页(zh-CN/en/ja/ko/de)各 200(web → SSR 整链);
    3. 化合物详情页 HCID 4 → 200(公开实体页 + BFF);
    4. MCP initialize 返回的 serverInfo.version 与仓库 VERSION 文件一致
       (MCP 协议入口 + 版本单一来源)。
    全部 fail closed; 不含 3xx 跟随(首页用无尾斜杠规范地址)。
    """
    ok_api, d1 = http_ok(PUBLIC_SMOKE_URL, headers=PUBLIC_SMOKE_HEADERS)
    _event("smoke.api", ok=ok_api, detail=d1)
    if not ok_api:
        return False

    for locale in SMOKE_LOCALES:
        ok_home, detail = _http_200(
            f"https://huagongshe.com/{locale}", PUBLIC_SMOKE_HEADERS)
        _event("smoke.home", locale=locale, ok=ok_home, detail=detail)
        if not ok_home:
            return False

    ok_page, detail = _http_200(SMOKE_CHEMICAL_PAGE, PUBLIC_SMOKE_HEADERS)
    _event("smoke.chemical_page", ok=ok_page, detail=detail)
    if not ok_page:
        return False

    ok_mcp, detail = _smoke_mcp_version()
    _event("smoke.mcp_version", ok=ok_mcp, detail=detail)
    return ok_mcp


def _smoke_mcp_version() -> tuple[bool, str]:
    """MCP initialize 的 serverInfo.version 必须等于仓库 VERSION 文件。

    /mcp 是 Streamable HTTP: 响应为 SSE 流(event: message + data: JSON),
    Accept 必须含 text/event-stream, 从 data: 行取 JSON-RPC result。
    """
    try:
        status, body = _http_post_json(SMOKE_MCP_URL, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "hgs-deploy-smoke", "version": "0"},
            },
        }, {**PUBLIC_SMOKE_HEADERS,
            "Accept": "application/json, text/event-stream"})
    except Exception as e:  # noqa: BLE001 — 冒烟 fail closed, 不抛出
        return False, f"error={e}"
    if status != 200:
        return False, f"status={status}"
    payload: dict | None = None
    for line in body.splitlines():
        if line.startswith("data:"):
            try:
                payload = json.loads(line[len("data:"):].strip())
            except Exception:  # noqa: BLE001
                payload = None
    if not payload:
        return False, "body=no-data-line"
    try:
        version = payload["result"]["serverInfo"]["version"]
    except Exception:  # noqa: BLE001
        return False, "body=no-serverInfo"
    repo_version = (REPO / "VERSION").read_text(encoding="utf-8").strip()
    if version != repo_version:
        return False, f"version={version} repo={repo_version}"
    return True, f"version={version}"


# ------------------------------------------------------------- deploy ------

def deploy(runner: Runner | None = None,
           skip_build: bool = False,
           readiness_timeout: float = 90.0) -> bool:
    """单实例发布: guard → build → start/restart 三 app → readiness → smoke → save。"""
    require_non_root()
    runner = runner or Runner.real()

    if not skip_build:
        _event("build.begin", target="web/.next")
        # 发布构建 fail-closed —— 只允许 npm ci（锁文件可重现）。
        # 不再回退 npm install：回退会让 lock 与实际安装树漂移，破坏可重现性。
        r = runner.run(["bash", "-lc",
                        "cd web && npm ci --no-audit --no-fund"
                        " && npx next build"])
        if r.returncode != 0:
            _event("build.failed")
            print((r.stdout or "")[-2000:], (r.stderr or "")[-2000:])
            return False
        _event("build.ok")

    for app in FRONTING_APPS:
        try:
            start_canonical(runner, app)
        except DeployError as e:
            _event("pm2.failed", app=app, error=str(e))
            return False

    if not wait_http_ok(API_HEALTH, timeout=readiness_timeout):
        _event("ready.failed", target="api", url=API_HEALTH)
        return False
    _event("ready.ok", target="api")
    if not wait_http_ok(WEB_HEALTH, timeout=readiness_timeout):
        _event("ready.failed", target="web", url=WEB_HEALTH)
        return False
    _event("ready.ok", target="web")

    # API 就绪后才重启 worker: 其启动 preflight 鉴权(/workapi/v1/jobs/lease)
    # 依赖 API, 提前重启只会 crash-loop。
    try:
        start_canonical(runner, WORKER_APP)
    except DeployError as e:
        _event("pm2.failed", app=WORKER_APP, error=str(e))
        return False
    if not wait_worker_online(runner):
        _event("ready.failed", target="worker")
        return False
    _event("ready.ok", target="worker")

    if not public_smoke():
        return False
    s = runner.run([pm2_argv(), "save"])
    if s.returncode != 0:
        _event("pm2.save.failed")
        return False
    _event("pm2.save.ok")
    _event("deploy.success")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ops.deploy",
                                 description="单实例部署 owner(无 blue/green)")
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--readiness-timeout", type=float, default=90.0)
    p.add_argument("--nginx-bootstrap", action="store_true",
                   help="一次性把 nginx 恢复为固定 upstream 8000/3001(幂等)")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印计划, 不执行任何 mutating 操作")
    a = p.parse_args(argv)

    if a.dry_run:
        _event("dryrun.plan", apps=list(CANONICAL_APPS), api_port=API_PORT,
               web_port=WEB_PORT, spec=str(SPEC), skip_build=a.skip_build,
               nginx_bootstrap=a.nginx_bootstrap)
        return 0
    try:
        if a.nginx_bootstrap:
            nginx_bootstrap(Runner.real())
            return 0
        return 0 if deploy(Runner.real(), skip_build=a.skip_build,
                           readiness_timeout=a.readiness_timeout) else 1
    except DeployError as e:
        _event("deploy.error", error=str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
