"""E8 部署编排测试替身 —— 全程不触碰真实 nginx / PM2 / 端口 / 生产文件。

模型:
  - FakeWorld: 谁在跑 / 谁 ready / nginx 当前指向哪一代(active upstream target);
    并提供 traffic probe 采样 `sample()` —— 采样到 "active target 无 live ready generation"
    即记录一次 violation(502 回归断言的判定点)。
  - FakeRunner: 解释 `pm2 ...` / `nginx ...` / `npm ...` argv, 可注入失败(启动失败、
    永不 ready、nginx 校验失败、reload 失败、构建失败、worker 未上线)。
  - FakeProber: 按 world 状态回答 readiness / 公网入口 / MCP initialize。
  - TrafficMonitor: 部署全程后台采样。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from ops.deploy import (
    ACTIVE_LINK,
    GENERATIONS,
    NGINX_GEN_TEMPLATE,
    Generation,
    Paths,
    Probe,
    Result,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# 现网 site config 的相关骨架(结构取自 /etc/nginx/sites-enabled/huagongshe 的 traffic 部分)
SITE_CONF_FIXTURE = """limit_req_zone $binary_remote_addr zone=hgs_api:10m rate=20r/s;

server {
    listen 443 ssl;
    server_name huagongshe.com;

    location = /mcp {
        proxy_pass http://127.0.0.1:8000;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:3001;
    }

    location / {
        proxy_pass http://127.0.0.1:3001;
    }
}
"""


def make_env(tmpdir: Path, *, version: str = "1.5.1", bootstrapped: bool = True) -> Paths:
    """搭一个隔离的临时部署环境(prod_root / nginx 骨架 / state 目录)。

    bootstrapped=True: site config 已是 install-nginx 迁移后的形态(含 active.conf include +
    upstream 名); False: 迁移前形态(硬编码 127.0.0.1:8000/3001)。
    """
    tmpdir = Path(tmpdir)
    prod = tmpdir / "prod"
    (prod / "web").mkdir(parents=True, exist_ok=True)
    (prod / "ecosystem.config.cjs").write_text(
        (REPO_ROOT / "ecosystem.config.cjs").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (prod / "VERSION").write_text(version + "\n", encoding="utf-8")

    nginx = tmpdir / "nginx"
    sites = nginx / "sites-enabled"
    sites.mkdir(parents=True, exist_ok=True)
    (nginx / "nginx.conf").write_text(
        "events {}\n"
        "http {\n"
        "    error_log /var/log/nginx/error.log;\n"
        f"    include {sites / '*'};"
        "\n}\n",
        encoding="utf-8",
    )
    gen_dir = nginx / "generations"
    site_text = SITE_CONF_FIXTURE
    if bootstrapped:
        site_text = site_text.replace("http://127.0.0.1:8000;", "http://hgs_api_active;")
        site_text = site_text.replace("http://127.0.0.1:3001;", "http://hgs_web_active;")
        site_text = f"include {gen_dir / ACTIVE_LINK};\n" + site_text
    site = sites / "huagongshe"
    site.write_text(site_text, encoding="utf-8")

    if bootstrapped:
        # bootstrap 形态: generation conf 已由 install-nginx 渲染
        # (B3 要求 active.conf 能解析到实体文件, 坏链必须被识别为无效状态)
        gen_dir.mkdir(parents=True, exist_ok=True)
        for gen in GENERATIONS.values():
            (gen_dir / f"{gen.name}.conf").write_text(
                NGINX_GEN_TEMPLATE.format(
                    gen=gen.name, api_port=gen.api_port, web_port=gen.web_port
                ),
                encoding="utf-8",
            )

    return Paths(
        prod_root=prod,
        nginx_conf=nginx / "nginx.conf",
        nginx_site_conf=site,
        nginx_gen_dir=gen_dir,
        state_dir=tmpdir / "state",
        use_sudo=False,
    )


def write_active_link(paths: Paths, gen: str) -> None:
    link = paths.nginx_gen_dir / "active.conf"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    os.symlink(f"{gen}.conf", link)


class FakeWorld:
    """部署世界状态(纯内存)。"""

    def __init__(self, version: str = "1.5.1") -> None:
        self.running = {name: False for name in GENERATIONS}
        self.started_at: dict[str, float] = {name: 0.0 for name in GENERATIONS}
        self.ready_delay = {name: 0.0 for name in GENERATIONS}
        self.never_ready = {name: False for name in GENERATIONS}
        self.worker_start_fail = {name: False for name in GENERATIONS}
        self.active = "blue"
        self.version = version
        self.violations: list[dict] = []
        self.samples = 0
        self.lock = threading.Lock()
        # nginx 进程模型(B2): reload 是否真的生效 = 是否出现新 worker PID
        self.nginx_master_pid = 4242
        self.nginx_workers: set[int] = {5001, 5002}
        self._next_worker_pid = 5100
        self.nginx_master_alive = True
        self.reload_applies = True
        self.reload_applies_sequence: list[bool] = []
        self.reload_attempts = 0
        self.reload_applied = 0

    # -- 生命周期 ---------------------------------------------------------- #
    def start(self, gen: str) -> None:
        with self.lock:
            self.running[gen] = True
            self.started_at[gen] = time.monotonic()

    def delete(self, gen: str) -> None:
        with self.lock:
            self.running[gen] = False

    def set_active(self, gen: str) -> None:
        with self.lock:
            self.active = gen

    def is_running(self, gen: str) -> bool:
        return self.running[gen]

    def is_ready(self, gen: str) -> bool:
        if not self.running[gen] or self.never_ready[gen]:
            return False
        return (time.monotonic() - self.started_at[gen]) >= self.ready_delay[gen]

    def worker_is_online(self, gen: str) -> bool:
        return self.running[gen] and not self.worker_start_fail[gen]

    def running_ports(self) -> set[int]:
        ports: set[int] = set()
        for gen, alive in self.running.items():
            if alive:
                ports.add(GENERATIONS[gen].api_port)
                ports.add(GENERATIONS[gen].web_port)
        return ports

    # -- nginx 进程模型 ---------------------------------------------------- #
    def rotate_nginx_workers(self) -> None:
        """reload 生效 → 新 worker 起来(旧 worker 允许仍在 graceful drain)。"""
        with self.lock:
            self._next_worker_pid += 2
            self.nginx_workers = {self._next_worker_pid, self._next_worker_pid + 1}

    def next_reload_applies(self) -> bool:
        with self.lock:
            self.reload_attempts += 1
            if self.reload_applies_sequence:
                return self.reload_applies_sequence.pop(0)
            return self.reload_applies

    def nginx_worker_pids(self) -> set[int]:
        with self.lock:
            return set(self.nginx_workers)

    # -- traffic probe 采样 ------------------------------------------------ #
    def sample(self) -> bool:
        """一次 traffic probe: active upstream target 是否落在 live + ready 的 generation 上。"""
        with self.lock:
            self.samples += 1
            active = self.active
            bad = not (self.running[active] and self.is_ready(active))
            if bad:
                self.violations.append(
                    {"active": active, "running": dict(self.running), "at": time.monotonic()}
                )
            return bad


class FakeRunner:
    """假命令执行器: 解释 pm2 / nginx / npm, 并驱动 FakeWorld。"""

    def __init__(
        self,
        world: FakeWorld,
        paths: Paths,
        *,
        build_code: int = 0,
        start_code: int = 0,
        validate_code: int = 0,
        reload_code: int = 0,
        delete_code: int = 0,
        pgrep_code: int = 0,
    ) -> None:
        self.world = world
        self.paths = paths
        self.build_code = build_code
        self.start_code = start_code
        self.validate_code = validate_code
        self.reload_code = reload_code
        self.delete_code = delete_code
        self.pgrep_code = pgrep_code
        self.argv_log: list[list[str]] = []
        self.cwd_log: list[str | None] = []
        self.env_log: list[dict] = []
        self.builds: list[dict] = []

    # -- 辅助 -------------------------------------------------------------- #
    @staticmethod
    def _gen_of_app(app: str) -> str | None:
        for name, gen in GENERATIONS.items():
            if app in gen.apps():
                return name
        return None

    def active_from_disk(self) -> str | None:
        link = self.paths.nginx_gen_dir / "active.conf"
        if not link.is_symlink():
            return None
        name = os.path.basename(os.readlink(link))
        name = name[: -len(".conf")] if name.endswith(".conf") else name
        return name if name in GENERATIONS else None

    def commands(self, *fragments: str) -> list[list[str]]:
        return [a for a in self.argv_log if all(f in " ".join(a) for f in fragments)]

    # -- 执行 -------------------------------------------------------------- #
    def run(self, argv, *, cwd=None, timeout: float = 300.0, env=None) -> Result:
        a = [str(x) for x in argv]
        self.argv_log.append(a)
        self.cwd_log.append(str(cwd) if cwd else None)
        self.env_log.append(dict(env or {}))

        if a[0] == "pgrep":
            if self.pgrep_code:
                return Result(a, self.pgrep_code, "")
            pattern = a[-1]
            if not self.world.nginx_master_alive:
                return Result(a, 1, "")
            if "worker" in pattern:
                return Result(a, 0, "\n".join(str(p) for p in sorted(self.world.nginx_worker_pids())))
            if "master" in pattern:
                return Result(a, 0, str(self.world.nginx_master_pid))
            return Result(a, 1, "")

        if a[0] == "npm":
            if self.build_code == 0 and cwd:
                # 真实 build 把产物写进 <cwd>/<distDir>(B1: 两代目录互不重叠)
                dist = dict(env or {}).get("HGS_NEXT_DIST_DIR", ".next")
                out = Path(cwd) / dist
                out.mkdir(parents=True, exist_ok=True)
                (out / "BUILD_ID").write_text(f"{dist}\n", encoding="utf-8")
                self.builds.append({"dist": dist, "cwd": str(cwd)})
            return Result(a, self.build_code, "")

        if "nginx" in a:
            if "-t" in a:
                return Result(a, self.validate_code, "nginx: configuration file test")
            if "-s" in a and "reload" in a:
                if self.reload_code:
                    self.world.reload_attempts += 1
                    return Result(a, self.reload_code, "reload failed")
                if not self.world.next_reload_applies():
                    # 信号成功但配置未生效: worker 不轮换, 运行中的 nginx 仍服务旧代
                    return Result(a, 0, "")
                gen = self.active_from_disk()
                if gen:
                    self.world.set_active(gen)
                self.world.rotate_nginx_workers()
                self.world.reload_applied += 1
                return Result(a, 0, "")
            if "-T" in a:
                gen = self.active_from_disk() or self.world.active
                g = GENERATIONS[gen]
                return Result(a, 0, f"upstream hgs_api_active {{ server 127.0.0.1:{g.api_port}; }}\n"
                                    f"upstream hgs_web_active {{ server 127.0.0.1:{g.web_port}; }}")
            return Result(a, 0, "")

        if a[0] == "install":
            # `install -d -o u -g u -m 0755 <dir>`(install-nginx 建 nginx generation 目录)
            target = Path(a[-1])
            target.mkdir(parents=True, exist_ok=True)
            return Result(a, 0, "")

        if a[0] == "pm2":
            sub = a[1]
            if sub == "start":
                gen = Path(a[2]).name
                gen = gen[len("ecosystem-"):-len(".cjs")]
                if self.start_code:
                    return Result(a, self.start_code, "start failed")
                self.world.start(gen)
                return Result(a, 0, "")
            if sub == "delete":
                for app in a[2:]:
                    g = self._gen_of_app(app)
                    if g:
                        self.world.delete(g)
                return Result(a, self.delete_code, "")
            if sub == "jlist":
                apps = []
                for name, gen in GENERATIONS.items():
                    if not self.world.is_running(name):
                        continue
                    for app in gen.apps():
                        status = "online"
                        if app == gen.worker_app and not self.world.worker_is_online(name):
                            status = "errored"
                        apps.append({"name": app, "pm2_env": {"status": status}})
                return Result(a, 0, json.dumps(apps))
            if sub == "save":
                return Result(a, 0, "")
            raise AssertionError(f"未预期的 pm2 子命令: {a}")

        raise AssertionError(f"未预期的命令: {a}")


class FakeProber:
    """假探针: 按 world 状态回答 readiness / 公网 / MCP。"""

    def __init__(self, world: FakeWorld, *, page_status: int = 200, mcp_status: int = 200) -> None:
        self.world = world
        self.page_status = page_status
        self.mcp_status = mcp_status
        self.calls: list[tuple] = []

    @staticmethod
    def _gen_for_port(port: int) -> str | None:
        for name, gen in GENERATIONS.items():
            if port in (gen.api_port, gen.web_port):
                return name
        return None

    def get(self, port: int, path: str, timeout=None) -> Probe:
        self.calls.append(("get", port, path))
        gen = self._gen_for_port(port)
        if gen and self.world.is_ready(gen):
            return Probe(ok=True, status=200, body=json.dumps({"status": "ok", "version": "1.0.0"}))
        return Probe(ok=False, status=503, body="", error="connection refused")

    def post(self, port: int, path: str, body: bytes, headers=None, timeout=None) -> Probe:
        self.calls.append(("post", port, path))
        return self.get(port, path, timeout)

    def public_get(self, path: str, timeout=None) -> Probe:
        self.calls.append(("public_get", path))
        if not self.world.is_ready(self.world.active):
            return Probe(ok=False, status=502, body="", error="upstream refused")
        if path == "/api/health":
            return Probe(ok=True, status=200, body=json.dumps({"status": "ok"}))
        return Probe(ok=True, status=self.page_status, body="<html><body>huagongshe</body></html>")

    def public_post(self, path: str, body: bytes, headers=None, timeout=None) -> Probe:
        self.calls.append(("public_post", path))
        if not self.world.is_ready(self.world.active):
            return Probe(ok=False, status=502, body="", error="upstream refused")
        if path == "/mcp":
            payload = {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"version": self.world.version}}}
            return Probe(ok=True, status=self.mcp_status, body=f"event: message\ndata: {json.dumps(payload)}\n\n")
        return Probe(ok=False, status=404, body="")


class TrafficMonitor:
    """部署全过程后台采样 traffic probe(模拟外部用户持续打 nginx)。"""

    def __init__(self, world: FakeWorld, interval: float = 0.002) -> None:
        self.world = world
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "TrafficMonitor":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.world.sample()
            time.sleep(self.interval)


def legacy_restart_sequence(world: FakeWorld, runner: FakeRunner, paths: Paths, *, gap: float = 0.15) -> None:
    """旧部署行为(被 E8 封住的缺陷): 先停旧代(端口失去 owner) → 再起新代 → 再切 upstream。

    等价于 fork 模式下 `pm2 reload` + 固定端口 nginx: 中间存在
    "active upstream target 没有 live ready generation" 的窗口。
    """
    old = world.active
    new = "green" if old == "blue" else "blue"
    runner.run([str(paths.pm2_bin), "delete", *GENERATIONS[old].apps()])
    time.sleep(gap)
    runner.run([str(paths.pm2_bin), "start", str(paths.state_dir / f"ecosystem-{new}.cjs"), "--only", ",".join(GENERATIONS[new].apps())])
    time.sleep(gap)
    write_active_link(paths, new)
    runner.run([str(paths.nginx_bin), "-s", "reload"])


def probe_generation(api_port: int, web_port: int) -> Generation:
    """给 readiness 测试用的临时 generation(用真实临时端口, 不碰生产端口)。"""
    return Generation("probe", "probe-api", "probe-web", "probe-worker", api_port, web_port)


def snapshot(root: Path) -> dict[str, str]:
    """目录树快照(相对路径 → 内容指纹/symlink 目标), 用于断言"什么都没被改动"。"""
    import hashlib

    root = Path(root)
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = "symlink:" + os.readlink(p)
        elif p.is_file():
            out[rel] = "file:" + hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        else:
            out[rel] = "dir"
    return out
