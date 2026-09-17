"""G1 final governance tests — family/scenario/contract 治理账本对账。

真实对象对账(禁止 registry 自证 registry):
- HTTP: 真实 FastAPI app route inventory ↔ scenario entrypoints(物理覆盖)
- MCP: build_mcp_server().list_tools() ↔ registry(14)
- WorkAPI: 真实 routes + ROUTE_SCOPE ↔ registry(10; 未知 scope fail-closed)
- agent-guide: 真实 payload 15 operations ↔ AGENT_HTTP 契约(语义匹配, 无序数模型)

guide auth 对账原则: guide auth 字符串 ↔ (scenario.auth, required_scope)
用显式语义映射, 每个合法组合逐条声明; 收紧仅当显式 selector scenario
(其语义由 guide input 文本载明, 如 mode!=exact / scope=mine)。
治理失败只导致本测试 failure, 不影响生产启动。
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://governance:governance@127.0.0.1:5432/unused",
)

from api.agent import agent_guide  # noqa: E402
from api.contracts import (  # noqa: E402
    AuthPolicy,
    Compatibility,
    Consumer,
    FAMILIES,
    Transport,
)
from api.workapi import ROUTE_SCOPE  # noqa: E402


# ---------------------------------------------------------------------------
# Registry 遍历 helpers
# ---------------------------------------------------------------------------

def all_scenarios():
    for fam in FAMILIES:
        for sc in fam.scenarios:
            yield fam, sc


def all_entrypoints():
    for fam, sc in all_scenarios():
        for ep in sc.entrypoints:
            yield fam, sc, ep


# ---------------------------------------------------------------------------
# Inventory helpers(测试专用; _IncludedRouter 兼容不污染生产代码)
# ---------------------------------------------------------------------------

def _iter_routes(app):
    for r in app.router.routes:
        if type(r).__name__ == "_IncludedRouter":
            prefix = (r.include_context.prefix or "") if r.include_context else ""
            for sub in r.original_router.routes:
                for m in (sub.methods or set()) - {"HEAD", "OPTIONS"}:
                    yield m, prefix + sub.path
        elif type(r).__name__ == "Mount":
            continue  # /mcp 子应用: MCP tool surface 由 MCP coverage 单独治理
        elif getattr(r, "methods", None):
            for m in r.methods - {"HEAD", "OPTIONS"}:
                yield m, r.path


def _app():
    from api.main import app
    return app


class RegistryIntegrity(unittest.TestCase):
    """账本完整性: 无重复场景绑定、无未用 policy、无逃生类型。"""

    def test_no_duplicate_scenario_binding(self):
        """同一 transport+name+selector 只能绑定一个 scenario。"""
        seen: dict[tuple, str] = {}
        for fam, sc, ep in all_entrypoints():
            key = (ep.transport, ep.name, ep.selector)
            self.assertNotIn(
                key, seen,
                f"重复场景绑定 {key}: {seen.get(key)} vs {fam.id}/{sc.id}")
            seen[key] = f"{fam.id}/{sc.id}"

    def test_scenario_id_unique_within_family(self):
        for fam in FAMILIES:
            ids = [s.id for s in fam.scenarios]
            self.assertEqual(len(ids), len(set(ids)),
                             f"{fam.id}: scenario id 重复")

    def test_no_unused_auth_policies(self):
        used = {sc.auth for _, sc in all_scenarios()}
        unused = [p for p in AuthPolicy if p not in used]
        self.assertEqual(unused, [],
                         f"未使用 AuthPolicy 必须删除: {[p.value for p in unused]}")

    def test_no_escape_hatch(self):
        banned = {"CUSTOM", "OTHER", "MISC", "UNKNOWN"}
        for p in AuthPolicy:
            self.assertNotIn(p.value, banned)

    def test_scenario_fields_complete(self):
        for fam, sc in all_scenarios():
            self.assertTrue(sc.entrypoints, f"{fam.id}/{sc.id}: 无 entrypoint")
            self.assertIsNotNone(sc.contract, f"{fam.id}/{sc.id}: 无 contract")

    def test_operation_id_single_physical_entry_per_transport(self):
        """operation identity 传输中立: 同一 operation_id 可覆盖多 transport 与
        同 route 的多个 selector scenario, 但同一 transport 内不得指向两个
        不同物理入口。"""
        by_oid: dict[str, dict[Transport, set[str]]] = {}
        for fam, sc in all_scenarios():
            oid = sc.contract.operation_id if sc.contract else None
            if not oid:
                continue
            per_transport = by_oid.setdefault(oid, {})
            for ep in sc.entrypoints:
                names = per_transport.setdefault(ep.transport, set())
                names.add(ep.name)
        for oid, per_transport in by_oid.items():
            for transport, names in per_transport.items():
                self.assertEqual(
                    len(names), 1,
                    f"operation_id {oid} 在 {transport.value} 指向多个物理入口: {names}")

    def test_kernel_members_exist(self):
        valid = {f"{fam.id}/{sc.id}" for fam, sc in all_scenarios()}
        for fam in FAMILIES:
            for k in fam.kernels:
                for member in k.members:
                    self.assertIn(member, valid,
                                  f"{fam.id}: kernel {k.kernel_id} 成员 {member} 不存在")

    def test_no_contractclass_leftovers(self):
        """ContractClass 已被 Compatibility(NONE/STABLE_EXTERNAL)取代,
        不得残留旧三值语义。"""
        import api.contracts.model as m
        self.assertFalse(hasattr(m, "ContractClass"))
        values = {p.value for p in Compatibility}
        self.assertEqual(values, {"NONE", "STABLE_EXTERNAL"})


class HttpPhysicalCoverage(unittest.TestCase):
    """物理 route 覆盖: 实际 routes(普通 HTTP)每个都被至少一个 scenario 绑定,
    且 scenario 声明的物理 route 都真实存在。不要求一对一(search/skills 反例)。"""

    def test_physical_routes_covered(self):
        actual = {(m + " " + p) for m, p in _iter_routes(_app())
                  if not p.startswith("/workapi/v1")}
        registered = {ep.name for _, _, ep in all_entrypoints()
                      if ep.transport is Transport.HTTP}
        unclassified = actual - registered
        phantom = registered - actual
        self.assertEqual(unclassified, set(),
                         f"未登记物理 route: {sorted(unclassified)}")
        self.assertEqual(phantom, set(),
                         f"幽灵登记(物理 route 不存在): {sorted(phantom)}")


class McpCoverage(unittest.TestCase):
    def test_mcp_tools_match_registry(self):
        from api.mcp_server import build_mcp_server
        tools = asyncio.run(build_mcp_server().list_tools())
        actual = {t.name for t in tools}
        registered = {ep.name for _, _, ep in all_entrypoints()
                      if ep.transport is Transport.MCP}
        self.assertEqual(len(actual), 14, f"MCP 必须为 14, 实际 {len(actual)}")
        self.assertEqual(actual - registered, set(),
                         f"MCP 未登记 tools: {sorted(actual - registered)}")
        self.assertEqual(registered - actual, set(),
                         f"MCP 幽灵登记: {sorted(registered - actual)}")

    def test_mcp_has_no_follow_tool(self):
        registered = {ep.name for _, _, ep in all_entrypoints()
                      if ep.transport is Transport.MCP}
        self.assertFalse(any("follow" in n for n in registered),
                         "基线无 MCP follow tool, 不得新增")


class WorkApiCoverage(unittest.TestCase):
    def test_workapi_routes_and_count(self):
        actual = {m + " " + p for m, p in _iter_routes(_app())
                  if p.startswith("/workapi/v1")}
        registered = {ep.name for _, _, ep in all_entrypoints()
                      if ep.transport is Transport.WORKAPI}
        self.assertEqual(len(actual), 10, f"WorkAPI 必须为 10, 实际 {len(actual)}")
        self.assertEqual(actual, registered, "WorkAPI routes 与 registry 漂移")

    def test_route_scope_matrix_matches_registry_scopes(self):
        """ROUTE_SCOPE 每个 (method,path) 的 scope 值必须与 registry required_scope
        精确一致; scope 值只允许 pubchem/cas(未知值 fail closed, 禁止 else→CAS)。"""
        allowed = {"pubchem", "cas"}
        reg = {}
        for fam, sc, ep in all_entrypoints():
            if ep.transport is Transport.WORKAPI:
                self.assertEqual(len(sc.required_scope), 1,
                                 f"{fam.id}/{sc.id}: WorkAPI scenario 必须恰好一个 scope")
                reg[ep.name] = sc.required_scope[0]
        self.assertEqual(set(reg), {f"{m} {p}" for m, p in ROUTE_SCOPE},
                         "ROUTE_SCOPE 键集与 registry 漂移")
        for (method, path), scope in ROUTE_SCOPE.items():
            key = f"{method} {path}"
            self.assertIn(scope, allowed,
                          f"未知 WorkAPI scope {scope!r} @ {key} — fail closed")
            self.assertEqual(reg[key], scope,
                             f"{key}: ROUTE_SCOPE={scope} 与 registry={reg[key]} 不一致")


class AgentGuideProjection(unittest.TestCase):
    """agent-guide = curated HTTP agent projection: 15 operations 与
    AGENT_HTTP 契约双向对账。授权用显式语义匹配(无序数模型):

    每条 guide auth 字符串声明其合法的 (auth policy, required_scope) 组合;
    selector 收紧场景(search 结构模式 / skills mine)是 guide input 文本
    载明的参数条件, 由带 selector 的 scenario 显式表达, 不走
    "更强 auth 也可以"的通配。
    """

    # guide auth 字符串 → 允许的 (AuthPolicy, required_scope) 精确组合
    SEMANTIC_MATCH = {
        "public": [
            (AuthPolicy.PUBLIC_OR_ACTOR, ()),
            (AuthPolicy.ANONYMOUS, ()),
        ],
        "public_or_bearer": [
            (AuthPolicy.PUBLIC_OR_ACTOR, ()),
        ],
        "bearer": [
            (AuthPolicy.ACTOR, ()),
        ],
        # 带 scope 的 guide auth: scope 必须逐字精确匹配
        "bearer:reaction:write": [
            (AuthPolicy.ACTOR, ("reaction:write",)),
        ],
        "bearer:skill:write": [
            (AuthPolicy.ACTOR, ("skill:write",)),
        ],
    }
    # guide input 文本载明的参数条件收紧(selector scenario 专属):
    #   search: mode!=exact 需登录(guide input: "结构检索需 AI Key", 等级收紧)
    #   skills: scope=mine 需登录(guide input: "mine 需 AI Key") —— 注意 guide
    #           把 mine 写在 operation 级 auth=public_or_bearer 下, mine 的
    #           ACTOR 语义是 input 文本内的参数条件, 同样属显式 selector 收紧。
    # 这两类收紧是显式登记的, 不是 generic "higher auth is okay"。
    SELECTOR_TIGHTENING_OK = {
        "search_chemistry_data": {"search/substructure", "search/similarity"},
        "list_skills": {"skill.read/list_mine"},
    }

    @classmethod
    def setUpClass(cls):
        cls.guide = asyncio.run(agent_guide(
            authorization=None, actor=None, db=_StubDb()))

    def _agent_http_contracts(self):
        """operation_id → 所有声明 AGENT_HTTP 的 scenario(selector 场景共享
        同一 guide operation, 必须全部返回)。"""
        out: dict[str, list] = {}
        for fam, sc in all_scenarios():
            if sc.contract and Consumer.AGENT_HTTP in sc.contract.consumers:
                oid = sc.contract.operation_id
                if oid:
                    out.setdefault(oid, []).append((fam, sc))
        return out

    def test_guide_has_15_operations(self):
        self.assertEqual(len(self.guide["operations"]), 15)

    def test_every_guide_op_has_matching_contract(self):
        reg = self._agent_http_contracts()
        for op in self.guide["operations"]:
            self.assertIn(op["id"], reg,
                          f"guide operation {op['id']} 无 AGENT_HTTP 契约")
            allowed = self.SEMANTIC_MATCH[op["auth"]]
            base_covered = False
            for fam, sc in reg[op["id"]]:
                https = [e for e in sc.entrypoints if e.transport is Transport.HTTP]
                self.assertTrue(https, f"{fam.id}/{sc.id}: 无 HTTP entrypoint")
                matched = any(
                    e.name == f"{op['method']} {op['path'].split('?')[0]}"
                    for e in https)
                self.assertTrue(
                    matched,
                    f"{op['id']}: guide {op['method']} {op['path']} "
                    f"与 {fam.id}/{sc.id} 入口不匹配")
                combo = (sc.auth, sc.required_scope)
                full_id = f"{fam.id}/{sc.id}"
                if combo in allowed:
                    base_covered = True  # 达到 guide 声明语义的基础场景
                else:
                    # 收紧场景: 只允许显式 selector scenario(参数条件)
                    self.assertIn(
                        full_id,
                        self.SELECTOR_TIGHTENING_OK.get(op["id"], set()),
                        f"{op['id']}/{full_id}: (auth={sc.auth.value}, "
                        f"scope={sc.required_scope}) 既不匹配 guide "
                        f"{op['auth']}, 也不是显式 selector 收紧场景")
            self.assertTrue(
                base_covered,
                f"{op['id']}: guide auth={op['auth']} 未被任何基础 scenario 满足")

    def test_no_phantom_agent_http_projection(self):
        guide_ids = {op["id"] for op in self.guide["operations"]}
        guide_ids.add("get_agent_connection_guide")  # guide 自身(自描述入口)
        phantom = set(self._agent_http_contracts()) - guide_ids
        self.assertEqual(phantom, set(),
                         f"registry 声明 AGENT_HTTP 但 guide 未公布: {sorted(phantom)}")


class CompatibilityLedger(unittest.TestCase):
    """兼容义务登记与已确认契约事实对账(与 Consumer 无推导关系)。"""

    def test_agent_guide_ops_are_stable(self):
        """guide 15 operations + guide 自身 → STABLE_EXTERNAL。"""
        guide_ids = {op["id"] for op in _guide_payload()["operations"]}
        guide_ids.add("get_agent_connection_guide")
        for fam, sc in all_scenarios():
            oid = sc.contract.operation_id if sc.contract else None
            if oid in guide_ids and Consumer.AGENT_HTTP in sc.contract.consumers:
                self.assertIs(
                    sc.contract.compatibility, Compatibility.STABLE_EXTERNAL,
                    f"{fam.id}/{sc.id}: guide operation {oid} 必须 STABLE_EXTERNAL")

    def test_all_mcp_tools_are_stable(self):
        """14 MCP tools → STABLE_EXTERNAL。"""
        stable = {ep.name for fam, sc in all_scenarios()
                  if sc.contract
                  and sc.contract.compatibility is Compatibility.STABLE_EXTERNAL
                  for ep in sc.entrypoints if ep.transport is Transport.MCP}
        self.assertEqual(stable, _mcp_tool_names(),
                         "MCP tool 的兼容义务必须全量 STABLE_EXTERNAL")

    def test_workapi_is_none(self):
        """WorkAPI = trusted internal protocol → Compatibility.NONE。"""
        for fam, sc, ep in all_entrypoints():
            if ep.transport is Transport.WORKAPI:
                self.assertIs(
                    sc.contract.compatibility, Compatibility.NONE,
                    f"{fam.id}/{sc.id}: WorkAPI 不得冒充 public compatibility")

    def test_web_admin_ops_are_none(self):
        """Web-only / Admin / OPS 场景 → NONE(无对外兼容义务)。"""
        for fam, sc in all_scenarios():
            cons = sc.contract.consumers
            if cons and cons <= {Consumer.WEB, Consumer.ADMIN, Consumer.OPS}:
                self.assertIs(
                    sc.contract.compatibility, Compatibility.NONE,
                    f"{fam.id}/{sc.id}: 纯内部面({cons})不得声明外部兼容义务")

    def test_discovery_does_not_imply_stable(self):
        """consumer=DISCOVERY 不自动稳定: PNG/datasets/sitemap 无稳定兼容承诺
        证据 → NONE; mol/rxn SVG 因 guide operation 而稳定, 与 DISCOVERY 无关。"""
        png = _find("molecule.rendering", "png")
        self.assertIs(png.contract.compatibility, Compatibility.NONE)
        self.assertIn(Consumer.DISCOVERY, png.contract.consumers)
        datasets = _find("dataset", "list")
        self.assertIs(datasets.contract.compatibility, Compatibility.NONE)
        sitemap = _find("discovery.sitemap", "reactions")
        self.assertIs(sitemap.contract.compatibility, Compatibility.NONE)


def _find(fam_id, sc_id):
    return next(f for f in FAMILIES if f.id == fam_id).scenario(sc_id)


def _guide_payload():
    return asyncio.run(agent_guide(authorization=None, actor=None, db=_StubDb()))


def _mcp_tool_names():
    from api.mcp_server import build_mcp_server
    return {t.name for t in asyncio.run(build_mcp_server().list_tools())}


class ScopeCorrectness(unittest.TestCase):
    """scope 机械检测 — reaction:write / skill:write 只出现在对应域。"""

    def test_reaction_write_scope_binding(self):
        holders = [f"{fam.id}/{sc.id}" for fam, sc in all_scenarios()
                   if "reaction:write" in sc.required_scope]
        self.assertEqual(
            holders,
            ["reaction.write/validate", "reaction.write/create"],
            f"reaction:write 错绑: {holders}")

    def test_skill_write_scope_binding(self):
        holders = [f"{fam.id}/{sc.id}" for fam, sc in all_scenarios()
                   if "skill:write" in sc.required_scope]
        self.assertEqual(
            holders,
            ["skill.write/validate", "skill.write/create"],
            f"skill:write 错绑: {holders}")

    def test_only_known_business_scopes(self):
        allowed = {"reaction:write", "skill:write", "pubchem", "cas"}
        for fam, sc in all_scenarios():
            for s in sc.required_scope:
                self.assertIn(s, allowed, f"{fam.id}/{sc.id}: 未知 scope {s}")


class FrozenScenarioShapes(unittest.TestCase):
    """G1A 冻结案例的机械断言(防退化)。"""

    def test_molecule_rendering_svg_png_split(self):
        fam = next(f for f in FAMILIES if f.id == "molecule.rendering")
        svg = fam.scenario("svg")
        png = fam.scenario("png")
        # 契约各自持有(PNG 不因 svg 进 guide 而获得 AGENT_HTTP/稳定义务)
        self.assertIn(Consumer.AGENT_HTTP, svg.contract.consumers)
        self.assertNotIn(Consumer.AGENT_HTTP, png.contract.consumers)
        self.assertIn(Consumer.DISCOVERY, png.contract.consumers)
        self.assertIs(svg.contract.compatibility, Compatibility.STABLE_EXTERNAL)
        self.assertIs(png.contract.compatibility, Compatibility.NONE)
        # 共享 kernel 显式登记(svg+png 双成员)
        kernels = {k.kernel_id: k for k in fam.kernels}
        self.assertEqual(set(kernels["render.kernel.molecule"].members),
                         {"molecule.rendering/svg", "molecule.rendering/png"})

    def test_search_three_selector_scenarios_share_kernel(self):
        fam = next(f for f in FAMILIES if f.id == "search")
        self.assertEqual({s.id for s in fam.scenarios},
                         {"exact", "substructure", "similarity"})
        exact = fam.scenario("exact")
        self.assertIs(exact.auth, AuthPolicy.PUBLIC_OR_ACTOR)
        self.assertIs(fam.scenario("substructure").auth, AuthPolicy.ACTOR)
        self.assertIs(fam.scenario("similarity").auth, AuthPolicy.ACTOR)
        k = next(k for k in fam.kernels if k.kernel_id == "search.service.unified")
        self.assertEqual(len(k.members), 3)

    def test_skills_list_two_scenarios_four_bindings(self):
        """skill.list 真实语义: HTTP/MCP 对称的 public/mine 两个 selector
        scenario, 四个 entrypoint binding 全部锁死。"""
        fam = next(f for f in FAMILIES if f.id == "skill.read")
        pub = fam.scenario("list_public")
        mine = fam.scenario("list_mine")
        self.assertIs(pub.auth, AuthPolicy.PUBLIC_OR_ACTOR)
        self.assertIs(mine.auth, AuthPolicy.ACTOR)
        self.assertEqual(
            {(e.transport, e.name, e.selector) for e in pub.entrypoints},
            {(Transport.HTTP, "GET /api/skills", "scope=public"),
             (Transport.MCP, "list_skills", "scope=public")})
        self.assertEqual(
            {(e.transport, e.name, e.selector) for e in mine.entrypoints},
            {(Transport.HTTP, "GET /api/skills", "scope=mine"),
             (Transport.MCP, "list_skills", "scope=mine")})
        k = next(k for k in fam.kernels if k.kernel_id == "skill.query.list")
        self.assertEqual(set(k.members), {"skill.read/list_public", "skill.read/list_mine"})

    def test_search_six_bindings(self):
        fam = next(f for f in FAMILIES if f.id == "search")
        bindings = {(e.transport, e.selector) for s in fam.scenarios
                    for e in s.entrypoints}
        self.assertEqual(bindings, {
            (Transport.HTTP, "mode=exact"),
            (Transport.HTTP, "mode=substructure"),
            (Transport.HTTP, "mode=similarity"),
            (Transport.MCP, "mode=exact"),
            (Transport.MCP, "mode=substructure"),
            (Transport.MCP, "mode=similarity"),
        })

    def test_reaction_create_single_transaction_multi_entry(self):
        fam = next(f for f in FAMILIES if f.id == "reaction.write")
        create = fam.scenario("create")
        self.assertEqual(create.required_scope, ("reaction:write",))
        transports = {e.transport for e in create.entrypoints}
        self.assertEqual(transports, {Transport.HTTP, Transport.MCP})
        self.assertIn(Consumer.WEB, create.contract.consumers)
        self.assertIn(Consumer.AGENT_MCP, create.contract.consumers)
        self.assertTrue(any(k.kernel_id == "reaction.tx.create" for k in fam.kernels))

    def test_reaction_rendering_cache_policy_independent(self):
        """reaction SVG 与 molecule SVG 属不同 family(缓存策略独立),
        且各自 contract 的 consumer 集合独立声明(无 family 级继承)。"""
        ids = {f.id for f in FAMILIES}
        self.assertIn("reaction.rendering", ids)
        self.assertIn("molecule.rendering", ids)
        rxn_svg = next(f for f in FAMILIES if f.id == "reaction.rendering").scenario("svg")
        mol_png = next(f for f in FAMILIES if f.id == "molecule.rendering").scenario("png")
        mol_svg = next(f for f in FAMILIES if f.id == "molecule.rendering").scenario("svg")
        self.assertNotIn(Consumer.AGENT_HTTP, mol_png.contract.consumers)
        self.assertIn(Consumer.AGENT_HTTP, mol_svg.contract.consumers)
        self.assertIn(Consumer.AGENT_MCP, rxn_svg.contract.consumers)

    def test_identity_workapi_uses_pubchem_scope(self):
        fam = next(f for f in FAMILIES if f.id == "worker.identity_jobs")
        for sc in fam.scenarios:
            self.assertEqual(sc.required_scope, ("pubchem",),
                             f"identity 沿用 pubchem scope(P1 维持现状), {sc.id} 漂移")


class NoRuntimeEnforcement(unittest.TestCase):
    def test_main_does_not_import_contracts(self):
        src = (REPO / "api" / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("contracts", src)
        self.assertNotIn("validate_api_surface", src)

    def test_contracts_do_not_import_frameworks(self):
        import ast
        banned_modules = {"fastapi", "mcp", "sqlalchemy"}
        banned_names = {"Request", "Response", "UploadFile"}
        for name in ("model", "registry", "__init__"):
            tree = ast.parse(
                (REPO / "api" / "contracts" / f"{name}.py").read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    mods = {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = {node.module.split(".")[0]}
                else:
                    continue
                self.assertFalse(mods & banned_modules,
                                 f"api/contracts/{name}.py 不得导入 {mods & banned_modules}")
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for a in node.names:
                        self.assertNotIn(a.name or a.asname, banned_names)


class _StubDb:
    async def execute(self, *_a, **_k):
        class _R:
            def scalar(self):
                return None
        return _R()


if __name__ == "__main__":
    unittest.main()
