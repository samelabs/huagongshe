""" —— worker 干净环境导入检查。

worker/main.py 的 aiohttp_socks 是函数级 import（启动时执行），纯
`import worker.main` 抓不到缺依赖崩溃。本脚本在当前解释器里解析
worker/*.py 的全部 import（含函数体内的），对每一个三方模块做真实
import 解析 —— 缺依赖即非零退出。

CI 用法（干净 venv）：
    python -m venv /tmp/worker-venv
    /tmp/worker-venv/bin/pip install -r requirements-worker.txt
    /tmp/worker-venv/bin/python scripts/check_worker_imports.py
"""
from __future__ import annotations

import ast
import importlib
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
# caslib / worker 是仓库根下的本地包 —— 干净 venv 里没有安装，须以仓库根为根解析
sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    stdlib = set(sys.stdlib_module_names)
    missing: list[str] = []
    for path in sorted(REPO_ROOT.joinpath("worker").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                if root in stdlib or root == "worker":
                    continue
                try:
                    importlib.import_module(name)
                except Exception as exc:  # noqa: BLE001 — 任何失败都是缺依赖证据
                    missing.append(f"{path.name}: import {name} → {type(exc).__name__}: {exc}")
    if missing:
        print("\n".join(missing))
        return 1
    import worker.main  # noqa: F401 — 模块级导入本身也必须成立
    print("worker import check ok: worker/*.py 的全部三方 import 在当前环境可解析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
