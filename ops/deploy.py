#!/usr/bin/env python3
"""计划部署编排(单一 owner) —— generation 切换, 不让 upstream 中断。

现状缺陷(2026-09-19 审计, 以仓库/主机事实为准):
  生产部署链 = `git ff-only` → `web build` → `pm2 reload <app>`;
  `ecosystem.config.cjs` 里 api/web 都是 **fork 模式**(无 `exec_mode: cluster`),
  `pm2 reload` 对 fork 应用等价于 restart: 旧进程先退出, 新进程之后才监听;
  而 nginx site config 是**固定端口**硬编码(`proxy_pass http://127.0.0.1:3001;` ×2,
  `/mcp` 用 `:8000`)—— 旧进程一退出, 该端口就没有 owner → nginx 502。

目标序列(本脚本实现):
    start new generation → readiness verified → switch traffic
    → verify traffic on new generation → drain old generation → stop old generation → smoke

失败窗口:
  - pre-switch(构建/启动/readiness/nginx 校验/切换本身失败)
      → 旧代继续服务 → 清理新代(流量未切)
  - post-switch(smoke / traffic verify 失败)
      → 切回旧代 → 验证旧代 → 停新代

边界(硬约束):
  - generation 逻辑只在 ops 层; 不改 application 代码, 不新增/改动任何端点。
  - 不跑 migration / 不碰 schema(本脚本无任何 migrate/psql/alembic 步骤)。
  - 不做多机 HA / LB 重设计 / 容器平台迁移 / PM2 替换 / nginx 架构重写。

B1 — 每代独立的 Next 构建产物:
  `web/next.config.ts` 的 distDir 读 `HGS_NEXT_DIST_DIR`(缺省 ".next"); 编排为每一代注入
  blue → `.next-blue`, green → `.next-green`, 构建与 `next start` 用同一个值。
  residual risk(已知并接受): 源码/`public` 等目录仍共享 —— E8 只保证
  "generation-specific Next build artifact", 不是完全不可变的 release 目录。

B2 — reload 的"已应用"判定:
  `nginx -s reload` exit 0 只代表信号送达。`reload_and_wait_applied()` 先抓 reload 前的
  nginx worker PID, 再发信号, 有界等待 master 仍存活 **且** 出现新 worker PID;
  两者都满足才算 applied(旧 worker 允许仍在 graceful drain)。只有 applied 之后才允许
  verify traffic → smoke → 停旧代; rollback 同样必须"恢复 symlink + 再次 reload + 等到
  applied", 否则 stage = rollback-failed(不得谎报旧代已恢复)。

B3 — generation state fail-closed:
  site config 没有 generation include = PRE-BOOTSTRAP(现网固定端口) → 现网 = blue;
  已有 include = BOOTSTRAPPED → active.conf 必须存在且指向 blue.conf/green.conf,
  缺失 / 坏链 / 未知 target = DeployError(绝不猜服务代)。install-nginx 在已有合法 active
  时保留当前 active, 不重置成 blue。

B4 — `--dry-run` 无副作用:
  不 build / 不 pm2 / 不 nginx / 不写 symlink 与 site config; 只做 read、内存渲染、
  静态校验与计划输出。
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Applied",
    "DeployError",
    "Deployer",
    "Generation",
    "GENERATIONS",
    "HttpProber",
    "Paths",
    "Probe",
    "Result",
    "Runner",
    "main",
    "parse_mcp_version",
    "render_spec_text",
]

# --------------------------------------------------------------------------- #
# generation 模型
#   本机最小双代: 每代 = 一对固定端口 + 一组 PM2 应用名。
#   blue = 现网(cold start 默认, 名字/端口与 ecosystem.config.cjs 一致)
#   green = 备用代(端口 +10, 名字带 -green 后缀)
#   两代在 traffic switch 之前必须同时存活。
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Generation:
    name: str
    api_app: str
    web_app: str
    worker_app: str
    api_port: int
    web_port: int

    def apps(self) -> tuple[str, ...]:
        return (self.api_app, self.web_app, self.worker_app)

    @property
    def next_dist_dir(self) -> str:
        """本代专属的 Next 构建产物目录(B1: 两代绝不共用 `.next`)。"""
        return f".next-{self.name}"


GENERATIONS: dict[str, Generation] = {
    "blue": Generation("blue", "huagongshe-api", "huagongshe", "huagongshe-pubchem-worker", 8000, 3001),
    "green": Generation(
        "green", "huagongshe-api-green", "huagongshe-green", "huagongshe-pubchem-worker-green", 8010, 3011
    ),
}
DEFAULT_GENERATION = "blue"
ACTIVE_LINK = "active.conf"
# B2: nginx 生效状态探测(pgrep 匹配 cmdline)
NGINX_WORKER_PATTERN = "nginx: worker process"
NGINX_MASTER_PATTERN = "nginx: master process"


class DeployError(RuntimeError):
    """编排无法安全继续(配置漂移 / 前置条件不满足)。"""


@dataclass(frozen=True)
class Paths:
    """部署涉及的全部路径与外部命令(测试注入临时目录 + 假命令)。"""

    prod_root: Path = Path("/var/www/huagongshe")
    nginx_conf: Path = Path("/etc/nginx/nginx.conf")
    nginx_site_conf: Path = Path("/etc/nginx/sites-enabled/huagongshe")
    nginx_gen_dir: Path = Path("/etc/nginx/hgs/generations")
    state_dir: Path = Path("/var/lib/huagongshe/deploy")
    nginx_bin: str = "nginx"
    pm2_bin: str = "pm2"
    npm_bin: str = "npm"
    pgrep_bin: str = "pgrep"
    use_sudo: bool = True
    public_host: str = "huagongshe.com"
    public_port: int = 443

    @property
    def web_dir(self) -> Path:
        return self.prod_root / "web"

    @property
    def ecosystem_conf(self) -> Path:
        return self.prod_root / "ecosystem.config.cjs"


# --------------------------------------------------------------------------- #
# 外部命令执行(可注入替身)
# --------------------------------------------------------------------------- #


@dataclass
class Result:
    argv: list[str]
    code: int
    out: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0


@dataclass(frozen=True)
class Applied:
    """nginx reload 是否真的生效(B2)。

    `ok=True` 才代表: 信号送达 **且** master 仍存活 **且** 观察到新 worker PID。
    """

    ok: bool
    reason: str = ""
    new_workers: tuple[int, ...] = ()


class Runner:
    """真 subprocess 执行; 测试注入 FakeRunner(记录 argv, 可注入失败)。"""

    def __init__(self, log=print) -> None:
        self._log = log

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 300.0,
        env: dict[str, str] | None = None,
    ) -> Result:
        import subprocess

        argv = [str(a) for a in argv]
        proc = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        self._log(f"    $ {' '.join(argv)}\n      exit={proc.returncode}")
        return Result(argv=argv, code=proc.returncode, out=out)


# --------------------------------------------------------------------------- #
# 真 HTTP 探针(不是"端口开着就算 ready")
# --------------------------------------------------------------------------- #


@dataclass
class Probe:
    ok: bool
    status: int | None = None
    body: str = ""
    error: str = ""

    def json(self):
        try:
            return json.loads(self.body)
        except Exception:
            return None


class HttpProber:
    """HTTP 探针。

    - `get/post`: 直连某一代端口(readiness / 判定是哪一代在答)。
    - `public_get/public_post`: 打本机 nginx 入口(127.0.0.1:443 + Host 头)验证用户流量路径。
      本机回环探针关闭 TLS 校验 —— 证书不是被测对象, 用 Host 头选 vhost。
    """

    def __init__(self, paths: Paths | None = None, timeout: float = 3.0) -> None:
        self.paths = paths or Paths()
        self.timeout = timeout

    def _request(
        self,
        *,
        host: str,
        port: int,
        path: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        tls: bool = False,
        timeout: float | None = None,
    ) -> Probe:
        tmo = self.timeout if timeout is None else timeout
        conn = None
        try:
            if tls:
                conn = http.client.HTTPSConnection(host, port, timeout=tmo, context=ssl._create_unverified_context())
            else:
                conn = http.client.HTTPConnection(host, port, timeout=tmo)
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            raw = resp.read()
            return Probe(ok=True, status=resp.status, body=raw.decode("utf-8", "replace"))
        except Exception as exc:  # 连接失败/超时 = 未 ready
            return Probe(ok=False, status=None, error=f"{type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def get(self, port: int, path: str, timeout: float | None = None) -> Probe:
        return self._request(host="127.0.0.1", port=port, path=path, timeout=timeout)

    def post(
        self,
        port: int,
        path: str,
        body: bytes,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Probe:
        return self._request(
            host="127.0.0.1", port=port, path=path, method="POST", body=body, headers=headers, timeout=timeout
        )

    def public_get(self, path: str, timeout: float | None = None) -> Probe:
        return self._request(
            host="127.0.0.1",
            port=self.paths.public_port,
            path=path,
            headers={"Host": self.paths.public_host},
            tls=True,
            timeout=timeout,
        )

    def public_post(
        self, path: str, body: bytes, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> Probe:
        hdrs = {"Host": self.paths.public_host}
        hdrs.update(headers or {})
        return self._request(
            host="127.0.0.1",
            port=self.paths.public_port,
            path=path,
            method="POST",
            body=body,
            headers=hdrs,
            tls=True,
            timeout=timeout,
        )


# --------------------------------------------------------------------------- #
# PM2 generation spec: 由 ecosystem.config.cjs 做**窄口径**替换得到
#   —— 单一事实源仍是 canonical 文件; 锚点缺失/数量不符 = 漂移 → fail-closed。
# --------------------------------------------------------------------------- #


def spec_substitutions(gen: Generation, paths: Paths) -> list[tuple[str, str, int]]:
    """(锚点, 替换, 期望出现次数)。任一条不满足 → DeployError。"""
    return [
        ('cwd: "/var/www/huagongshe/web",', f'cwd: "{paths.web_dir}",', 1),
        ('cwd: "/var/www/huagongshe",', f'cwd: "{paths.prod_root}",', 2),
        ('name: "huagongshe-api",', f'name: "{gen.api_app}",', 1),
        ('name: "huagongshe",', f'name: "{gen.web_app}",', 1),
        ('name: "huagongshe-pubchem-worker",', f'name: "{gen.worker_app}",', 1),
        ("--port 8000 ", f"--port {gen.api_port} ", 1),
        ('next start -H 127.0.0.1 -p 3001"', f'next start -H 127.0.0.1 -p {gen.web_port}"', 1),
        ('HGS_WORKAPI_URL: "http://127.0.0.1:8000"', f'HGS_WORKAPI_URL: "http://127.0.0.1:{gen.api_port}"', 1),
        ('HGS_WORKER_ID: "server-local-1"', f'HGS_WORKER_ID: "server-local-1-{gen.name}"', 1),
        (
            'NODE_ENV: "production",',
            'NODE_ENV: "production",\n'
            f'        API_ORIGIN_INTERNAL: "http://127.0.0.1:{gen.api_port}",\n'
            f'        HGS_NEXT_DIST_DIR: "{gen.next_dist_dir}",',
            1,
        ),
        # 有界 graceful stop: SIGINT → kill_timeout → SIGKILL
        ('interpreter: "none",', 'interpreter: "none",\n      kill_timeout: 10000,', 3),
    ]


def render_spec_text(gen: Generation, canonical_text: str, paths: Paths) -> str:
    """按 generation 渲染 PM2 spec 文本(端口/名字/worker 指向)。"""
    out = canonical_text
    for anchor, replacement, expected in spec_substitutions(gen, paths):
        count = out.count(anchor)
        if count != expected:
            raise DeployError(
                f"ecosystem.config.cjs 漂移: 锚点 {anchor!r} 出现 {count} 次(期望 {expected}); 拒绝生成 spec"
            )
        out = out.replace(anchor, replacement)
    header = f"// 由 ops/deploy.py 生成 —— 不要手改。generation={gen.name}\n"
    return header + out


# nginx generation 文件(upstream 定义, http 上下文)
NGINX_GEN_TEMPLATE = """# 由 ops/deploy.py 生成 —— 不要手改。generation={gen}
upstream hgs_api_active {{
    server 127.0.0.1:{api_port};
}}
upstream hgs_web_active {{
    server 127.0.0.1:{web_port};
}}
"""

# 现网 site config 里固定端口 proxy_pass 的一次性迁移锚点
SITE_PROXY_REWRITES: tuple[tuple[str, str], ...] = (
    ("proxy_pass http://127.0.0.1:8000;", "proxy_pass http://hgs_api_active;"),
    ("proxy_pass http://127.0.0.1:3001;", "proxy_pass http://hgs_web_active;"),
)

MCP_INITIALIZE_BODY = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "ops-deploy", "version": "1"},
        },
    }
).encode()

MCP_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def parse_mcp_version(body: str) -> str | None:
    """从 MCP initialize 响应取 serverInfo.version(兼容 SSE 与纯 JSON)。"""
    payload = body
    if "data:" in payload:
        chunks = [ln[len("data:"):].strip() for ln in payload.splitlines() if ln.startswith("data:")]
        payload = chunks[-1] if chunks else payload
    try:
        data = json.loads(payload)
    except Exception:
        return None
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict):
        info = result.get("serverInfo") or {}
        version = info.get("version")
        if isinstance(version, str):
            return version
    return None


# --------------------------------------------------------------------------- #
# 编排主体
# --------------------------------------------------------------------------- #


class Deployer:
    def __init__(
        self,
        *,
        paths: Paths | None = None,
        runner: Runner | None = None,
        prober: HttpProber | None = None,
        log=print,
        readiness_timeout: float = 90.0,
        readiness_interval: float = 1.0,
        drain_grace: float = 5.0,
        stop_timeout: float = 15.0,
        skip_build: bool = False,
        dry_run: bool = False,
        reload_timeout: float = 10.0,
    ) -> None:
        self.paths = paths or Paths()
        self.log = log
        self.runner = runner or Runner(log=log)
        self.prober = prober or HttpProber(self.paths)
        self.readiness_timeout = readiness_timeout
        self.readiness_interval = readiness_interval
        self.drain_grace = drain_grace
        self.stop_timeout = stop_timeout
        self.skip_build = skip_build
        self.dry_run = dry_run
        self.reload_timeout = reload_timeout
        self.events: list[tuple[str, dict]] = []

    # -- 事件(测试断言顺序用) ---------------------------------------------- #
    def _event(self, name: str, **kw) -> None:
        self.events.append((name, kw))
        detail = " ".join(f"{k}={v}" for k, v in kw.items())
        self.log(f"  [{name}] {detail}".rstrip())

    def event_names(self) -> list[str]:
        return [name for name, _ in self.events]

    def _ran(self, *fragments: str) -> list[str]:
        """已执行命令的 argv 列表(测试用于证明没有 migration 类步骤)。"""
        return [a for r in self.events if r[0] == "cmd" for a in [r[1]["argv"]]]

    # -- 命令封装 ---------------------------------------------------------- #
    def _sudo(self, argv: list[str]) -> list[str]:
        return ["sudo", "-n", *argv] if self.paths.use_sudo else list(argv)

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        timeout: float = 300.0,
        env: dict[str, str] | None = None,
    ) -> Result:
        argv = [str(a) for a in argv]
        self.events.append(("cmd", {"argv": argv, "env": env or {}}))
        if self.dry_run:
            self.log(f"    (dry-run) {' '.join(argv)}")
            return Result(argv=argv, code=0)
        return self.runner.run(argv, cwd=cwd, timeout=timeout, env=env)

    def _nginx(self, *args: str) -> Result:
        return self._run(self._sudo([self.paths.nginx_bin, *args]))

    def _pm2(self, *args: str) -> Result:
        return self._run([self.paths.pm2_bin, *args])

    # -- 事实读取 ---------------------------------------------------------- #
    def active_link(self) -> Path:
        return self.paths.nginx_gen_dir / ACTIVE_LINK

    def active_generation(self) -> str | None:
        """当前 active generation; 缺失 / 坏链(目标文件不存在) / 未知 target 一律 None。"""
        link = self.active_link()
        if not link.is_symlink():
            return None
        try:
            target = os.readlink(link)
        except OSError:
            return None
        name = os.path.basename(target)
        if name.endswith(".conf"):
            name = name[: -len(".conf")]
        if name not in GENERATIONS:
            return None
        return name if link.exists() else None

    def site_bootstrapped(self) -> bool:
        """site config 是否已含 generation include(B3: 区分 PRE-BOOTSTRAP 与状态丢失)。"""
        try:
            text = self.paths.nginx_site_conf.read_text(encoding="utf-8")
        except OSError as exc:
            raise DeployError(f"读不到 site config {self.paths.nginx_site_conf}: {exc}") from exc
        return str(self.active_link()) in text

    def require_active(self) -> str:
        """服务代的唯一判定入口(B3)。

        PRE-BOOTSTRAP(site 仍是固定端口) → 现网 = blue(记 active.assumed);
        BOOTSTRAPPED 但 active.conf 缺失/坏链/未知 target → DeployError(fail-closed, 不猜)。
        """
        active = self.active_generation()
        if active:
            return active
        if self.site_bootstrapped():
            raise DeployError(
                "site config 已 bootstrap 但 active.conf 缺失/坏链/未知 target "
                f"({self.active_link()}); 拒绝猜测服务代 —— 人工修复, 或跑 `ops/deploy.py install-nginx`"
            )
        self._event("active.assumed", gen=DEFAULT_GENERATION, reason="pre-bootstrap(site 仍是固定端口)")
        return DEFAULT_GENERATION

    @staticmethod
    def other_generation(gen: str) -> str:
        return "green" if gen == "blue" else "blue"

    # -- 步骤 0: web 构建 -------------------------------------------------- #
    def build(self, gen: Generation) -> bool:
        """构建**目标代**专属产物(B1); dry-run 不构建(B4)。"""
        if self.dry_run:
            self._event("build.skipped", gen=gen.name, reason="dry-run", dist=gen.next_dist_dir)
            return True
        self._event("build.begin", gen=gen.name, dir=str(self.paths.web_dir), dist=gen.next_dist_dir)
        r = self._run(
            [self.paths.npm_bin, "run", "build"],
            cwd=self.paths.web_dir,
            timeout=900.0,
            env={"HGS_NEXT_DIST_DIR": gen.next_dist_dir},
        )
        if not r.ok:
            self._event("build.failed", gen=gen.name, code=r.code)
            return False
        self._event("build.ok", gen=gen.name, dist=gen.next_dist_dir)
        return True

    # -- 步骤 1: 起新代 ---------------------------------------------------- #
    def render_spec(self, gen: Generation) -> Path:
        canonical_text = self.paths.ecosystem_conf.read_text(encoding="utf-8")
        text = render_spec_text(gen, canonical_text, self.paths)
        out = self.paths.state_dir / f"ecosystem-{gen.name}.cjs"
        if not self.dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        self._event("spec.rendered", gen=gen.name, path=str(out))
        return out

    def start_generation(self, gen: Generation) -> bool:
        spec = self.render_spec(gen)
        self._event("start.begin", gen=gen.name)
        # 目标代按定义不是服务代: 先清掉可能残留的同代进程, 保证 env 完全来自渲染后的 spec
        self._pm2("delete", *gen.apps())
        # PM2 7.x 的 --only 不接受 comma-joined 多 app 名(会把 spec 文件本身
        # 当脚本启动成单个 fork 进程): 按 gen.apps() 顺序逐 app 独立 start。
        for app in gen.apps():
            r = self._pm2("start", str(spec), "--only", app)
            if not r.ok:
                self._event("start.failed", gen=gen.name, code=r.code, app=app)
                return False
        self._event("start.ok", gen=gen.name, apps=list(gen.apps()))
        return True

    def pm2_statuses(self) -> dict[str, str]:
        r = self._pm2("jlist")
        if not r.ok:
            return {}
        try:
            data = json.loads(r.out.strip())
        except Exception:
            return {}
        out: dict[str, str] = {}
        if isinstance(data, list):
            for app in data:
                if isinstance(app, dict) and isinstance(app.get("name"), str):
                    env = app.get("pm2_env") if isinstance(app.get("pm2_env"), dict) else {}
                    out[app["name"]] = str(env.get("status") or "")
        return out

    def verify_worker(self, gen: Generation) -> bool:
        """新代的 worker 也必须活着(否则这一代不完整, 不切流量)。

        fail-closed: jlist 失败(空 statuses)、列表为空、worker 缺失、
        worker 非 online 一律不得判成功——只有目标 generation worker
        明确 online 才 PASS。dry-run 不实际启动 PM2, 显式返回 PASS。
        """
        if self.dry_run:
            self._event("worker.verify.ok", gen=gen.name, dry_run=True)
            return True
        self._event("worker.verify.begin", gen=gen.name)
        deadline = time.monotonic() + self.stop_timeout
        while True:
            statuses = self.pm2_statuses()
            if statuses.get(gen.worker_app) == "online":
                self._event("worker.verify.ok", gen=gen.name, status="online")
                return True
            if time.monotonic() >= deadline:
                self._event(
                    "worker.verify.failed",
                    gen=gen.name,
                    status=statuses.get(gen.worker_app, "missing" if not statuses else "unknown"),
                )
                return False
            time.sleep(0.5)

    # -- 步骤 2: 真 readiness --------------------------------------------- #
    def _health_ok(self, port: int) -> bool:
        probe = self.prober.get(port, "/api/health")
        if not probe.ok or probe.status != 200:
            return False
        data = probe.json()
        return isinstance(data, dict) and data.get("status") == "ok"

    def wait_ready(self, gen: Generation) -> bool:
        """API 代直接答 `/api/health`; web 代经自己的 BFF(`/api/[...path]`)答同一端点。

        后者同时证明: web 进程能服务 + 该 web 代连到的是"自己这一代"的 API
        (`API_ORIGIN_INTERNAL` 指向本代 api 端口)。
        """
        self._event("ready.begin", gen=gen.name, timeout=self.readiness_timeout)
        if self.dry_run:
            self._event("ready.ok", gen=gen.name, dry_run=True)
            return True
        deadline = time.monotonic() + self.readiness_timeout
        while True:
            api_ok = self._health_ok(gen.api_port)
            web_ok = api_ok and self._health_ok(gen.web_port)
            if api_ok and web_ok:
                self._event("ready.ok", gen=gen.name)
                return True
            if time.monotonic() >= deadline:
                self._event("ready.timeout", gen=gen.name, api=api_ok, web=web_ok)
                return False
            time.sleep(self.readiness_interval)

    # -- 步骤 3: nginx 候选校验 + 原子切换 --------------------------------- #
    def render_nginx_generation(self, gen: Generation) -> Path:
        path = self.paths.nginx_gen_dir / f"{gen.name}.conf"
        text = NGINX_GEN_TEMPLATE.format(gen=gen.name, api_port=gen.api_port, web_port=gen.web_port)
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        self._event("nginx.generation.rendered", gen=gen.name, path=str(path))
        return path

    def validate_candidate(self, gen: Generation) -> bool:
        """用**临时 config 树**验证候选 upstream: 不动线上文件, 不先破坏旧 upstream。"""
        self.render_nginx_generation(gen)
        site = self.paths.nginx_site_conf.read_text(encoding="utf-8")
        main = self.paths.nginx_conf.read_text(encoding="utf-8")
        include_line = str(self.active_link())
        if include_line not in site:
            raise DeployError(
                f"site config 未 bootstrap(缺少 {include_line}); 先跑 `ops/deploy.py install-nginx`"
            )
        if str(self.paths.nginx_site_conf.parent / "*") not in main:
            raise DeployError(f"nginx 主配置未 include {self.paths.nginx_site_conf.parent}/*, 无法验证候选")
        with tempfile.TemporaryDirectory(prefix="hgs-nginx-candidate-") as tmp:
            tmpdir = Path(tmp)
            (tmpdir / "sites").mkdir()
            candidate = self.paths.nginx_gen_dir / f"{gen.name}.conf"
            (tmpdir / "sites" / self.paths.nginx_site_conf.name).write_text(
                site.replace(str(self.active_link()), str(candidate)), encoding="utf-8"
            )
            main_tmp = main.replace(
                str(self.paths.nginx_site_conf.parent / "*"), str(tmpdir / "sites" / "*")
            )
            # 测试 config 不该写线上 error_log
            main_tmp = "\n".join(
                ln for ln in main_tmp.splitlines() if not ln.strip().startswith("error_log")
            )
            main_path = tmpdir / "nginx.conf"
            main_path.write_text(main_tmp, encoding="utf-8")
            self._event("nginx.validate.begin", gen=gen.name, config=str(main_path))
            r = self._nginx("-t", "-c", str(main_path))
            if not r.ok:
                self._event("nginx.validate.failed", gen=gen.name, code=r.code)
                return False
            self._event("nginx.validate.ok", gen=gen.name)
            return True

    # -- B2: nginx reload 的"已应用"判定 ------------------------------------ #
    def _pgrep(self, pattern: str) -> set[int] | None:
        """匹配 cmdline 的 PID 集合; None = 无法判定(命令不可用/非 0/1 退出)。"""
        r = self._run([self.paths.pgrep_bin, "-f", pattern])
        if r.code not in (0, 1):  # pgrep: 1 = 无匹配
            self._event("nginx.probe.unavailable", pattern=pattern, code=r.code)
            return None
        return {int(tok) for tok in r.out.split() if tok.isdigit()}

    def nginx_worker_pids(self) -> set[int] | None:
        return self._pgrep(NGINX_WORKER_PATTERN)

    def nginx_master_alive(self) -> bool | None:
        pids = self._pgrep(NGINX_MASTER_PATTERN)
        return None if pids is None else bool(pids)

    def reload_and_wait_applied(self) -> Applied:
        """发 reload 信号 + 有界等待"配置真的生效"(B2)。

        判定 = 信号 exit 0 **且** master 仍存活 **且** 出现 reload 前不存在的 worker PID。
        旧 worker 允许仍在 graceful drain, 不要求它立即消失。
        """
        if self.dry_run:
            self._event("reload.skipped", reason="dry-run")
            return Applied(True, "dry-run")
        before = self.nginx_worker_pids()
        if before is None:
            # 拿不到 reload 前的 worker 视图 → 无法证明"已应用" → fail-closed
            return Applied(False, "probe-unavailable")
        r = self._nginx("-s", "reload")
        if not r.ok:
            self._event("reload.signal.failed", code=r.code)
            return Applied(False, f"signal-exit-{r.code}")
        deadline = time.monotonic() + self.reload_timeout
        while True:
            master = self.nginx_master_alive()
            if master is False:
                self._event("reload.master_gone")
                return Applied(False, "master-gone")
            workers = self.nginx_worker_pids()
            if workers:
                fresh = tuple(sorted(workers - before))
                if fresh:
                    self._event("reload.applied", new_workers=list(fresh))
                    return Applied(True, "applied", fresh)
            if time.monotonic() >= deadline:
                self._event("reload.not_applied", timeout=self.reload_timeout)
                return Applied(False, "no-new-worker")
            time.sleep(self.readiness_interval)

    def _replace_active_link(self, gen: str) -> None:
        """同目录临时 symlink + `os.replace` —— 原子替换 active upstream target。"""
        link = self.active_link()
        tmp = link.with_name(f"{ACTIVE_LINK}.tmp")
        if tmp.exists() or tmp.is_symlink():
            tmp.unlink()
        os.symlink(f"{gen}.conf", tmp)
        os.replace(tmp, link)

    def apply_generation(self, gen: Generation, previous: str | None = None) -> Applied:
        """原子边界: symlink rename → reload → 等到 applied(B2)。

        失败时把 symlink 恢复成 `previous` 并**再次 reload**(让"磁盘 = 运行"重新成立);
        若这次恢复 reload 也没生效, reason 带 `+restore-not-applied`(不谎报已恢复)。
        """
        self._event("switch.begin", gen=gen.name)
        if self.dry_run:
            self._event("switch.applied", gen=gen.name, dry_run=True)
            self._event("switch.ok", gen=gen.name, dry_run=True)
            return Applied(True, "dry-run")
        self._replace_active_link(gen.name)
        applied = self.reload_and_wait_applied()
        if applied.ok:
            self._event("switch.applied", gen=gen.name, new_workers=list(applied.new_workers))
            self._event("switch.ok", gen=gen.name)
            return applied
        self._event("switch.failed", gen=gen.name, reason=applied.reason)
        if previous and previous in GENERATIONS:
            # 运行中的 nginx 仍是旧配置(新配置未生效): 磁盘 symlink 回到旧代 + 再次 reload
            self._replace_active_link(previous)
            self._event("switch.restored", gen=previous)
            back = self.reload_and_wait_applied()
            if back.ok:
                self._event("switch.restore.reload.ok", gen=previous)
            else:
                self._event("switch.restore.reload.failed", gen=previous, reason=back.reason)
                return Applied(False, f"{applied.reason}+restore-not-applied")
        return applied

    def switch_traffic(self, gen: Generation, previous: str | None = None) -> bool:
        return self.apply_generation(gen, previous=previous).ok

    def verify_traffic(self, gen: Generation) -> bool:
        """确认流量已落在新代: active symlink + nginx 生效配置端口 + 公网入口可答。"""
        if self.dry_run:
            self._event("traffic.verify.ok", gen=gen.name, dry_run=True)
            return True
        active = self.active_generation()
        if active != gen.name:
            self._event("traffic.verify.failed", gen=gen.name, reason=f"active={active}")
            return False
        dump = self._nginx("-T")
        if not dump.ok or f"127.0.0.1:{gen.api_port}" not in dump.out or f"127.0.0.1:{gen.web_port}" not in dump.out:
            self._event("traffic.verify.failed", gen=gen.name, reason="nginx -T 未指向新代端口")
            return False
        probe = self.prober.public_get("/api/health")
        if not probe.ok or probe.status != 200:
            self._event("traffic.verify.failed", gen=gen.name, reason=f"public={probe.status} {probe.error}")
            return False
        self._event("traffic.verify.ok", gen=gen.name)
        return True

    # -- 步骤 4: smoke(readiness / 普通 HTTP / MCP 基本可达) --------------- #
    def smoke(self) -> dict:
        if self.dry_run:
            self._event("smoke.ok", dry_run=True)
            return {"ok": True, "checks": {}, "dry_run": True}
        checks: dict[str, dict] = {}

        health = self.prober.public_get("/api/health")
        data = health.json()
        checks["readiness"] = {
            "ok": bool(
                health.ok and health.status == 200 and isinstance(data, dict) and data.get("status") == "ok"
            ),
            "status": health.status,
            "error": health.error,
        }

        page = self.prober.public_get("/")
        checks["http"] = {
            "ok": bool(page.ok and page.status == 200 and page.body.strip()),
            "status": page.status,
            "error": page.error,
        }

        mcp = self.prober.public_post("/mcp", MCP_INITIALIZE_BODY, MCP_HEADERS)
        version = parse_mcp_version(mcp.body) if mcp.ok else None
        expected = self.expected_version()
        mcp_ok = bool(mcp.ok and mcp.status == 200 and version)
        if mcp_ok and expected:
            mcp_ok = version == expected
        checks["mcp"] = {"ok": mcp_ok, "status": mcp.status, "version": version, "error": mcp.error}

        ok = all(c["ok"] for c in checks.values())
        self._event("smoke.ok" if ok else "smoke.failed", **{k: v["ok"] for k, v in checks.items()})
        return {"ok": ok, "checks": checks}

    def expected_version(self) -> str | None:
        try:
            return (self.paths.prod_root / "VERSION").read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    # -- 步骤 5: drain + 停旧代(只在 switch + smoke 之后) ------------------ #
    def drain_and_stop(self, gen: Generation) -> bool:
        """旧代退出必须晚于 traffic switch + post-switch smoke。"""
        self._event("drain.begin", gen=gen.name, grace=self.drain_grace)
        if self.dry_run:
            self._event("drain.stopped", gen=gen.name, dry_run=True)
            return True
        # 流量已切走(reload 后不再引用旧 upstream); 给 nginx 旧 worker 的在途请求一个有界窗口
        if self.drain_grace > 0:
            time.sleep(self.drain_grace)
        r = self._pm2("delete", *gen.apps())
        if not r.ok:
            self._event("drain.stop.failed", gen=gen.name, code=r.code)
        self._wait_gone(gen)
        self._event("drain.stopped", gen=gen.name)
        return True

    def _wait_gone(self, gen: Generation) -> None:
        deadline = time.monotonic() + self.stop_timeout
        while time.monotonic() < deadline:
            statuses = self.pm2_statuses()
            if not statuses:
                return
            if all(statuses.get(app) != "online" for app in gen.apps()):
                return
            time.sleep(0.5)
        self._event("drain.force", gen=gen.name)
        self._pm2("delete", *gen.apps())

    def cleanup_failed(self, gen: Generation) -> None:
        """清理失败的新代(只删新代, 绝不碰正在服务的旧代)。"""
        self._event("cleanup.begin", gen=gen.name)
        self._pm2("delete", *gen.apps())
        self._event("cleanup.done", gen=gen.name)

    def pm2_save(self) -> None:
        self._event("pm2.save.begin")
        self._pm2("save")
        self._event("pm2.save.done")

    # -- 编排 -------------------------------------------------------------- #
    def deploy(self, target: str | None = None) -> dict:
        active = self.require_active()  # B3: fail-closed, 绝不把 None 猜成 blue
        if target is None:
            target = self.other_generation(active)
        if target == active:
            raise DeployError(f"目标代与当前服务代相同({target}); 同端口无法两代并存")
        target_gen = GENERATIONS[target]
        active_gen = GENERATIONS[active]
        self._event("deploy.begin", active=active, target=target, version=self.expected_version())

        if not self.skip_build and not self.build(target_gen):
            return self._pre_switch_failure(active, target, "build")

        if not self.start_generation(target_gen):
            return self._pre_switch_failure(active, target, "start")
        if not self.verify_worker(target_gen):
            return self._pre_switch_failure(active, target, "worker")
        if not self.wait_ready(target_gen):
            return self._pre_switch_failure(active, target, "readiness")
        if not self.validate_candidate(target_gen):
            return self._pre_switch_failure(active, target, "nginx-validation")
        if not self.apply_generation(target_gen, previous=active).ok:
            return self._pre_switch_failure(active, target, "switch")
        if not self.verify_traffic(target_gen):
            return self._rollback_post_switch(active_gen, target_gen, "traffic-verify")

        smoke = self.smoke()
        if not smoke["ok"]:
            return self._rollback_post_switch(active_gen, target_gen, "smoke", smoke)

        # 只有 traffic 已从旧代移走 + post-switch smoke 通过, 旧代才允许退出
        self.drain_and_stop(active_gen)
        self.pm2_save()
        self._event("deploy.success", active=target, stopped=active)
        return {
            "ok": True,
            "stage": "success",
            "active": target,
            "stopped": active,
            "traffic_switched": True,
            "smoke": smoke,
        }

    def _pre_switch_failure(self, active: str, target: str, reason: str) -> dict:
        self._event("deploy.pre_switch_failure", reason=reason, active=active, target=target)
        self.cleanup_failed(GENERATIONS[target])
        return {
            "ok": False,
            "stage": "pre-switch",
            "reason": reason,
            "active": active,
            "stopped": None,
            "traffic_switched": False,
        }

    def _rollback_post_switch(
        self, old: Generation, new: Generation, reason: str, smoke: dict | None = None
    ) -> dict:
        self._event("rollback.begin", reason=reason, to=old.name)
        # B2: 恢复 symlink + 再次 reload + 等到 applied, 才谈"旧代已恢复"
        applied = self.apply_generation(old, previous=new.name)
        if not applied.ok:
            self._event("rollback.failed", to=old.name, reason=applied.reason)
            return {
                "ok": False,
                "stage": "rollback-failed",
                "reason": reason,
                "active": new.name,
                "old_verified": False,
                "stopped": None,
                "traffic_switched": True,
                "rollback_error": applied.reason,
                "smoke": smoke,
            }
        old_ok = self.verify_traffic(old)
        self.cleanup_failed(new)
        self._event("rollback.done", to=old.name, old_verified=old_ok)
        return {
            "ok": False,
            "stage": "post-switch-rollback",
            "reason": reason,
            "active": old.name,
            "old_verified": old_ok,
            "stopped": new.name,
            "traffic_switched": True,
            "smoke": smoke,
        }

    # -- 一次性 nginx 迁移(bootstrap, 幂等) -------------------------------- #
    def install_nginx(self) -> dict:
        gen_dir = self.paths.nginx_gen_dir
        self._event("install.begin", gen_dir=str(gen_dir))
        if self.dry_run:
            self._event("install.dry_run")
            return {"ok": True, "dry_run": True}

        user = os.environ.get("USER") or "ubuntu"
        self._run(self._sudo(["install", "-d", "-o", user, "-g", user, "-m", "0755", str(gen_dir)]))

        # B3: 已有**合法** active → 保留(不重置成 blue); 缺失/坏链/未知 target → 初始化 blue。
        # 判定必须在渲染 generation conf 之前: 渲染会把缺失的 blue.conf/green.conf 补回来,
        # 那样"坏链"会看起来变合法(从而保留一个并非当初写入的状态)。
        link = self.active_link()
        current = self.active_generation()
        link_changed = False
        if current is None:
            if link.exists() or link.is_symlink():
                link.unlink()
            os.symlink(f"{DEFAULT_GENERATION}.conf", link)
            link_changed = True
            self._event("install.active_link.initialized", gen=DEFAULT_GENERATION)
        else:
            self._event("install.active_link.preserved", gen=current)

        for gen in GENERATIONS.values():
            self.render_nginx_generation(gen)

        site = self.paths.nginx_site_conf
        original = site.read_text(encoding="utf-8")
        desired = self._patched_site_config(original)
        if desired == original and not link_changed:
            self._event("install.site_config.unchanged", path=str(site))
            return {
                "ok": True,
                "changed": False,
                "active": current or DEFAULT_GENERATION,
                "link_changed": False,
            }

        backup: Path | None = None
        if desired != original:
            # 备份必须位于 nginx include 目录之外(sites-enabled/* 会被 nginx
            # 当正式配置加载, 历史事故: .bak 同名 limit_req_zone 导致 nginx -t
            # 必败)。固定放 HGS nginx 配置根 nginx_gen_dir.parent(/etc/nginx/hgs/)。
            backup_dir = self.paths.nginx_gen_dir.parent
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f"{site.name}.bak-{int(time.time())}"
            backup.write_text(original, encoding="utf-8")
            self._event("install.site_config.backup", path=str(backup))
            site.write_text(desired, encoding="utf-8")
        r = self._nginx("-t")
        if not r.ok:
            if desired != original:
                site.write_text(original, encoding="utf-8")
                self._event("install.site_config.rolled_back", code=r.code)
            raise DeployError("site config 校验失败, 已回滚(线上流量未受影响)")
        self._nginx("-s", "reload")
        self._event("install.site_config.updated", path=str(site))
        return {
            "ok": True,
            "changed": True,
            "backup": str(backup) if backup else None,
            "active": self.active_generation(),
            "link_changed": link_changed,
        }

    def _patched_site_config(self, text: str) -> str:
        include_line = f"include {self.active_link()};"
        out = text
        for old, new in SITE_PROXY_REWRITES:
            count = out.count(old)
            if count == 0:
                if out.count(new) > 0:
                    continue  # 已迁移过(幂等)
                raise DeployError(f"site config 架构漂移: 找不到 {old!r}(需先人工确认)")
            out = out.replace(old, new)
            self._event("install.rewrite", frm=old, to=new, count=count)
        if include_line not in out:
            out = include_line + "\n" + out
            self._event("install.include.added", line=include_line)
        return out

    # -- 只读状态 ---------------------------------------------------------- #
    def status(self) -> dict:
        out: dict = {"active": self.active_generation(), "generations": {}}
        for name, gen in GENERATIONS.items():
            api = self.prober.get(gen.api_port, "/api/health")
            web = self.prober.get(gen.web_port, "/api/health")
            out["generations"][name] = {
                "api_port": gen.api_port,
                "web_port": gen.web_port,
                "api_ready": bool(api.ok and api.status == 200),
                "web_ready": bool(web.ok and web.status == 200),
            }
        return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ops.deploy", description="generation 部署编排(blue/green)")
    p.add_argument("command", nargs="?", default="deploy", choices=["deploy", "install-nginx", "status"])
    p.add_argument("--to", choices=sorted(GENERATIONS), default=None, help="目标 generation(默认取非当前代)")
    p.add_argument("--skip-build", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--prod-root", default=str(Paths.prod_root))
    p.add_argument("--nginx-conf", default=str(Paths.nginx_conf))
    p.add_argument("--nginx-site-conf", default=str(Paths.nginx_site_conf))
    p.add_argument("--nginx-gen-dir", default=str(Paths.nginx_gen_dir))
    p.add_argument("--state-dir", default=str(Paths.state_dir))
    p.add_argument("--no-sudo", action="store_true")
    p.add_argument("--readiness-timeout", type=float, default=90.0)
    p.add_argument("--readiness-interval", type=float, default=1.0)
    p.add_argument("--drain-grace", type=float, default=5.0)
    p.add_argument("--reload-timeout", type=float, default=10.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = Paths(
        prod_root=Path(args.prod_root),
        nginx_conf=Path(args.nginx_conf),
        nginx_site_conf=Path(args.nginx_site_conf),
        nginx_gen_dir=Path(args.nginx_gen_dir),
        state_dir=Path(args.state_dir),
        use_sudo=not args.no_sudo,
    )
    logger = (lambda *a, **k: None) if args.json else print
    deployer = Deployer(
        paths=paths,
        log=logger,
        readiness_timeout=args.readiness_timeout,
        readiness_interval=args.readiness_interval,
        drain_grace=args.drain_grace,
        skip_build=args.skip_build,
        dry_run=args.dry_run,
        reload_timeout=args.reload_timeout,
    )
    try:
        if args.command == "install-nginx":
            result = deployer.install_nginx()
        elif args.command == "status":
            result = deployer.status()
        else:
            result = deployer.deploy(target=args.to)
    except DeployError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, default=str))
    if args.command == "status":
        return 0
    if result.get("ok"):
        return 0
    return 2 if result.get("stage") == "pre-switch" else 3


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
