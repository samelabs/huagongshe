"""单实例部署 owner(v1.5.2 R4-SINGLE)。

职责(仅此而已):
  1. fail-closed 检查执行用户不是 root(mutating deploy 禁 root)
  2. build Web(单一 canonical `.next`)
  3. 使用仓库根 `ecosystem.config.cjs`(canonical, 不生成任何 spec)
  4. restart/start canonical API/Web/Worker(单一 PM2 daemon = 当前用户)
  5. readiness: API 8000 health / Web 3001 health / worker online
  6. public smoke + `pm2 save`

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
    "huagongshe-api",       # API  127.0.0.1:8000
    "huagongshe",           # Web  127.0.0.1:3001
    "huagongshe-pubchem-worker",  # worker, HGS_WORKER_ID=server-local-1
)
API_PORT = 8000
WEB_PORT = 3001
API_HEALTH = f"http://127.0.0.1:{API_PORT}/api/health"
WEB_HEALTH = f"http://127.0.0.1:{WEB_PORT}/api/health"
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


@dataclass
class Runner:
    """subprocess 执行器; 测试注入 FakeRunner 替代。"""

    run: Callable[[list[str]], "subprocess.CompletedProcess"]

    @classmethod
    def real(cls) -> "Runner":
        def _run(argv: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(argv, capture_output=True, text=True)
        return cls(run=_run)


# ---------------------------------------------------------------- guards --

def require_non_root() -> None:
    """mutating deploy 禁 root: root 会把 app 落进 root PM2 daemon(生产事故根因之一)。"""
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
        r = runner.run([pm2_argv(), "restart", app, "--update-env"])
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


def wait_worker_online(runner: Runner, timeout: float = 60.0,
                       poll: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if worker_online(runner):
            return True
        time.sleep(poll)
    return False


# -------------------------------------------------------------- readiness --

def http_ok(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read(256).decode("utf-8", "replace")
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

def public_smoke() -> bool:
    """公网面最小 smoke(API health + MCP version)。经 nginx 固定 upstream。"""
    ok_api, d1 = http_ok("http://127.0.0.1/api/health")
    _event("smoke.api", ok=ok_api, detail=d1)
    return ok_api


# ------------------------------------------------------------- deploy ------

def deploy(runner: Runner | None = None,
           skip_build: bool = False,
           readiness_timeout: float = 90.0) -> bool:
    """单实例发布: guard → build → start/restart 三 app → readiness → smoke → save。"""
    require_non_root()
    runner = runner or Runner.real()

    if not skip_build:
        _event("build.begin", target="web/.next")
        r = runner.run(["bash", "-lc",
                        "cd web && (npm ci --no-audit --no-fund || npm install --no-audit --no-fund)"
                        " && npx next build"])
        if r.returncode != 0:
            _event("build.failed")
            print((r.stdout or "")[-2000:], (r.stderr or "")[-2000:])
            return False
        _event("build.ok")

    for app in CANONICAL_APPS:
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
