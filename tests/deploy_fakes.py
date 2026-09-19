"""单实例部署 owner 的最小测试 fake + 回归锁(R4-SINGLE)。

FakeRunner 模拟最小 PM2/nginx 世界:
  - jlist 返回实际已启动的 app(不凭空发明)
  - `pm2 start <spec> --only <app>` 只启动该 app, 且 app 必须在 spec 内
  - `pm2 restart/save` 记录 argv
  - `nginx -t`/`-s reload` 恒成功(bootstrap 语义由回归锁单独覆盖)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class FakeRunner:
    apps: dict[str, dict] = field(default_factory=dict)   # name -> {"status": ...}
    argv_log: list[list[str]] = field(default_factory=list)
    spec_apps: tuple[str, ...] = (
        "huagongshe-api", "huagongshe", "huagongshe-pubchem-worker",
    )
    http_ok_urls: set[str] = field(default_factory=set)   # readiness 会成功的 URL
    build_ok: bool = True
    restart_fail: set[str] = field(default_factory=set)   # restart 报失败的 app
    jlist_fail: bool = False

    _pid_seq: int = 100

    def _next_pid(self) -> int:
        # dataclass field 不可变默认→用实例属性懒初始化
        if not hasattr(self, "_pid_counter"):
            self._pid_counter = 100
        self._pid_counter += 1
        return self._pid_counter

    # --- Runner 协议 -------------------------------------------------------
    def run(self, argv: list[str]) -> subprocess.CompletedProcess:
        self.argv_log.append(list(argv))
        cmd = argv[0]
        if cmd == "bash" and "next build" in (argv[-1] or ""):
            code = 0 if self.build_ok else 1
            return _cp(code, "" if code == 0 else "build failed")
        if cmd == "pm2":
            return self._pm2(argv[1:])
        if cmd in ("sudo",):
            if "nginx" in argv:
                return _cp(0, "nginx ok")
            return _cp(0, "")
        if cmd == "curl":
            return _cp(0, "")
        return _cp(0, "")

    # --- PM2 语义 ----------------------------------------------------------
    def _pm2(self, args: list[str]) -> subprocess.CompletedProcess:
        if args[0] == "jlist":
            if self.jlist_fail:
                return _cp(1, "pm2 daemon unavailable")
            out = json.dumps([
                {"name": n, "pid": v.get("pid", 100),
                 "pm2_env": {"status": v["status"], "pm_id": v.get("pm_id", 0),
                             "pid": v.get("pid", 100)}}
                for n, v in self.apps.items()
            ])
            return _cp(0, out)
        if args[0] in ("start", "restart"):
            if args[0] == "start":
                # pm2 start <spec> --only <app>: spec 内该 app 才启动
                only = args[args.index("--only") + 1] if "--only" in args else None
                if "," in (only or ""):
                    return _cp(1, "invalid single --only")   # 禁 comma
                if only is not None and only not in self.spec_apps:
                    return _cp(1, f"app {only} not in spec")
                self.apps[only] = {"status": "online",
                                   "pid": self._next_pid(), "pm_id": 0}
                return _cp(0, f"started {only}")
            target = args[1]
            if target in self.restart_fail:
                return _cp(1, f"restart {target} failed")
            if target not in self.apps:
                return _cp(1, f"{target} not found")
            self.apps[target]["status"] = "online"
            self.apps[target]["pid"] = self._next_pid()
            return _cp(0, f"restarted {target}")
        if args[0] == "save":
            return _cp(0, "saved")
        return _cp(1, "unknown pm2 subcommand")

    # --- 断言辅助 ----------------------------------------------------------
    def pm2_start_only_cmds(self) -> list[list[str]]:
        return [c for c in self.argv_log
                if len(c) > 1 and c[0] == "pm2" and c[1] == "start"]

    def pm2_save_called(self) -> bool:
        return any(c[:2] == ["pm2", "save"] for c in self.argv_log)


def _cp(code: int, out: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=out,
                                       stderr="" if code == 0 else out)
