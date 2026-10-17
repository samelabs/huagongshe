"""前端取数查询参数名与后端端点声明参数名的静态对账。

前端调用 apiGet/apiPost 等时手写的查询串（如 ?page=1&page_size=20）
没有任何类型联系，参数名写错会被后端静默忽略（或回落默认值），行为
漂移且契约测试测不到。本对账从两端各自的真实来源提取：
- 后端：api.main.app 的全部 APIRoute，签名里不属于路径的参数即 Query 参数；
- 前端：web 源码中取数调用首参字符串里的查询参数名。
规则：每个能对上路由的前端调用，其参数名必须是该端点声明的参数名
子集（分页、过滤全部如此）。对不上的路径模板（拼接式 URL）跳过。
"""

from __future__ import annotations

import inspect
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def _iter_api_routes(routes):
    """展平路由树（include 的子路由挂在 original_router.routes 下）。"""
    from fastapi.routing import APIRoute

    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        else:
            for nested in (getattr(route, "routes", None),
                           getattr(getattr(route, "original_router", None), "routes", None)):
                if nested:
                    yield from _iter_api_routes(nested)


def _backend_query_params() -> dict[tuple[str, str], set[str]]:
    """(method, 归一化路径) → 该端点声明的查询参数名集合。"""
    from api.main import app

    table: dict[tuple[str, str], set[str]] = {}
    for route in _iter_api_routes(app.routes):
        path = route.path
        endpoint = route.endpoint
        methods = route.methods or set()
        normalized = re.sub(r"\{[^}]+\}", "{v}", path)
        try:
            signature = inspect.signature(endpoint)
        except (TypeError, ValueError):
            continue
        path_param_names = set(re.findall(r"\{([^}]+)\}", path))
        query_names = set()
        for name, param in signature.parameters.items():
            if name in {"request", "db", "response", "background_tasks"}:
                continue
            if name in path_param_names:
                continue
            # pydantic Body 模型（无默认值且为复杂类型）与 Depends 不算 Query
            if param.default is inspect.Parameter.empty and param.annotation not in (int, float, str, bool):
                continue
            query_names.add(name)
        for method in methods - {"HEAD", "OPTIONS"}:
            key = (method, normalized)
            table.setdefault(key, set()).update(query_names)
    return table


def _frontend_calls() -> list[tuple[str, str, str, int]]:
    """扫描 web 源码取数调用 → (method, 归一化路径, 参数名, 行号)。"""
    fetch_re = re.compile(
        r"api(Get|Post|Put|Patch|Delete)(?:<[^>]*>)?\(\s*[`\"']([^`\"'?]+)(?:\?([^`\"']*))?[`\"']")
    calls: list[tuple[str, str, str, int]] = []
    for area in ("app", "components", "lib"):
        for file in (WEB_ROOT / area).rglob("*"):
            if not file.is_file() or file.suffix not in (".ts", ".tsx"):
                continue
            if ".test." in file.name:
                continue
            text = file.read_text(encoding="utf-8")
            for match in fetch_re.finditer(text):
                lineno = text.count("\n", 0, match.start()) + 1
                method = {"Get": "GET", "Post": "POST", "Put": "PUT", "Patch": "PATCH", "Delete": "DELETE"}[match.group(1)]
                base = re.sub(r"\$\{[^}]*\}", "{v}", match.group(2))
                query = match.group(3) or ""
                for chunk in query.split("&"):
                    name = chunk.split("=")[0].strip()
                    if not name or "${" in name:
                        continue
                    calls.append((method, base, name, lineno))
    return calls


class FrontendQueryNameContractTests(unittest.TestCase):
    def test_query_names_subset_of_backend_declaration(self):
        table = _backend_query_params()
        self.assertGreater(len(table), 50, "路由表应覆盖全部 API 端点")
        violations: list[str] = []
        matched = 0
        for method, base, name, lineno in _frontend_calls():
            key = (method, base)
            if key not in table:
                continue  # 拼接式/非直连路径不在本对账范围
            matched += 1
            if name not in table[key]:
                violations.append(f"{method} {base}?{name} (行 {lineno})")
        self.assertGreater(matched, 50, "对账应命中足量真实调用")
        self.assertEqual(
            violations, [],
            "前端查询参数名不是后端声明参数名：\n  " + "\n  ".join(violations))


if __name__ == "__main__":
    unittest.main()
