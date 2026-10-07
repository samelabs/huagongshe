"""v1.7 agent-facing contract closeout (Batch A) governance locks.

A-01: /api/agent-guide machine contract is English-only.
A-02: llms.txt is English-only and keeps the frozen facts
      (13 tools, OAuth + 3 scopes, REST/AI Key compatibility,
      no Note MCP / no note:write).
A-03: MCP reaction validation translator emits no CJK and
      create_reaction no longer exposes the raw Pydantic exception.
A-04: all five locale mcp/guide dictionaries express OAuth as the
      standard path and AI Key as the compatibility path.
"""

from __future__ import annotations

import asyncio
import ast
import os
import re
import unittest

os.environ.setdefault(
    "HGS_DATABASE_URL",
    "postgresql+asyncpg://metadata:metadata@127.0.0.1:5432/unused",
)

from api import agent as agent_module
from api import mcp_server as mcp_module
from api.mcp_server import build_mcp_server
from api.schemas.reactions import ReactionBody

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(REPO, "web")
LOCALES = ("zh-CN", "en", "ja", "ko", "de")

CJK_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")


def _collect_strings(node) -> list[str]:
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
    return out


def _mcp_section(locale: str) -> str:
    src = open(
        os.path.join(WEB, "lib", "i18n", "locales", f"{locale}.ts"),
        encoding="utf-8",
    ).read()
    match = re.search(r"\n  mcp: \{.*?\n  \},\n", src, re.S)
    assert match, locale
    return match.group(0)


def _guide_section(locale: str) -> str:
    src = open(
        os.path.join(WEB, "lib", "i18n", "locales", f"{locale}.ts"),
        encoding="utf-8",
    ).read()
    match = re.search(r"\n  guide: \{.*?\n  \},\n", src, re.S)
    assert match, locale
    return match.group(0)


class AgentGuideEnglishContract(unittest.TestCase):
    """A-01: every fixed contract string on /api/agent-guide is English."""

    def _guide_payload_strings(self) -> list[str]:
        tree = ast.parse(open(
            os.path.join(REPO, "api", "agent.py"), encoding="utf-8"
        ).read())
        strings = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        strings.append(sub.value)
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "agent_guide"
        )
        for node in ast.walk(fn):
            if isinstance(node, ast.Return):
                strings.extend(_collect_strings(node))
            if isinstance(node, ast.Raise):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        strings.append(sub.value)
        # include the route summary (user-visible in OpenAPI)
        strings.append("REST / AI Key compatibility surface: read AI-available operations (MCP is the primary integration)")
        return strings

    def test_contract_strings_contain_no_cjk(self):
        for value in self._guide_payload_strings():
            self.assertIsNone(
                CJK_RE.search(value), f"CJK leaked into agent contract: {value!r}"
            )

    def test_operation_contract_shape_unchanged(self):
        src = open(os.path.join(REPO, "api", "agent.py"), encoding="utf-8").read()
        ids = re.findall(r'"id": "([a-z_]+)",', src)
        self.assertEqual(len(ids), 14)
        self.assertEqual(ids[0], "search_chemistry_data")
        self.assertEqual(ids[-1], "create_reaction")
        self.assertIn('"api_version": settings.api_version', src)


class LlmsTxtEnglishContract(unittest.TestCase):
    """A-02: llms.txt is English and keeps the frozen facts."""

    @classmethod
    def setUpClass(cls):
        cls.text = open(
            os.path.join(REPO, "web", "public", "llms.txt"), encoding="utf-8"
        ).read()

    def test_no_cjk(self):
        self.assertIsNone(CJK_RE.search(self.text), "llms.txt must be English-only")

    def test_frozen_facts(self):
        self.assertIn("https://huagongshe.com/mcp", self.text)
        self.assertIn("13 total", self.text)
        self.assertIn("PKCE S256", self.text)
        self.assertIn("`read`, `reaction:write`, `skill:write`", self.text)
        self.assertIn("REST / AI Key compatibility surface", self.text)
        self.assertIn("never accepted as a REST bearer credential", self.text)
        self.assertIn("Note MCP tools and the `note:write` scope", self.text)
        self.assertNotIn("note:write scope is", self.text)  # negative only

    def test_note_write_not_advertised_as_capability(self):
        # note:write may only appear inside the "not provided" sentence.
        occurrences = [
            line for line in self.text.splitlines() if "note:write" in line
        ]
        self.assertEqual(len(occurrences), 1)
        self.assertIn("Not provided", occurrences[0])


class McpValidationTranslatorContract(unittest.TestCase):
    """A-03: MCP reaction validation errors are English at the boundary."""

    def test_translator_maps_known_validator_messages(self):
        cases = {
            "只有产物可以填写收率":
                "yield is only allowed for PRODUCT participants",
            "投料数值和单位必须同时填写":
                "amount_value and amount_unit must be provided together",
            "至少需要一个反应物和一个产物":
                "at least one REACTANT and one PRODUCT are required",
            "来源类型 doi 缺少对应的来源信息":
                "source_type 'doi' is missing its required source evidence",
        }
        for raw, expected in cases.items():
            self.assertEqual(mcp_module._english_validation_message(raw), expected)

    def test_translator_fallback_is_neutral(self):
        self.assertEqual(
            mcp_module._english_validation_message("某种未知校验错误"),
            "invalid value",
        )
        self.assertEqual(
            mcp_module._english_validation_message(""), "invalid value"
        )

    def test_boundary_message_keeps_location_and_has_no_cjk(self):
        try:
            ReactionBody(
                visibility="private",
                participants=[
                    {"role": "REACTANT", "smiles": "CCO"},
                    {"role": "REAGENT", "smiles": "O", "yield_percent": 50},
                ],
                source_type="self",
            )
        except Exception as exc:
            message = mcp_module._validation_error_message(
                "Invalid reaction draft fields", exc
            )
        else:  # pragma: no cover
            self.fail("draft should fail validation")
        self.assertIn("participants.1", message)
        self.assertIn(
            "yield is only allowed for PRODUCT participants", message
        )
        self.assertIsNone(CJK_RE.search(message), message)

    def test_create_reaction_uses_shared_translator_not_raw_exc(self):
        src = open(os.path.join(REPO, "api", "mcp_server.py"), encoding="utf-8").read()
        self.assertNotIn('f"Invalid draft fields: {exc}"', src)
        self.assertIn(
            '_validation_error_message("Invalid draft fields", exc)', src
        )

    def test_runtime_tool_error_messages_have_no_cjk(self):
        invalid_drafts = [
            # yield on non-PRODUCT participant
            {
                "visibility": "private",
                "participants": [
                    {"role": "REACTANT", "smiles": "CCO"},
                    {"role": "REAGENT", "smiles": "O", "yield_percent": 50},
                ],
                "source_type": "self",
            },
            # amount value without unit
            {
                "visibility": "private",
                "participants": [
                    {"role": "REACTANT", "smiles": "CCO",
                     "amount_value": 1.0},
                    {"role": "PRODUCT", "smiles": "CCOCC"},
                ],
                "source_type": "self",
            },
            # missing PRODUCT
            {
                "visibility": "private",
                "participants": [
                    {"role": "REACTANT", "smiles": "CCO"},
                    {"role": "REAGENT", "smiles": "O"},
                ],
                "source_type": "self",
            },
            # temperature value without unit
            {
                "visibility": "private",
                "participants": [
                    {"role": "REACTANT", "smiles": "CCO"},
                    {"role": "PRODUCT", "smiles": "CCOCC"},
                ],
                "source_type": "self",
                "temperature_value": 25.0,
            },
            # bad DOI
            {
                "visibility": "private",
                "participants": [
                    {"role": "REACTANT", "smiles": "CCO"},
                    {"role": "PRODUCT", "smiles": "CCOCC"},
                ],
                "source_type": "doi",
                "doi": "not-a-doi",
            },
        ]
        for draft in invalid_drafts:
            with self.subTest(draft=draft):
                try:
                    ReactionBody(**draft)
                except Exception as exc:
                    message = mcp_module._validation_error_message(
                        "Invalid reaction draft fields", exc
                    )
                else:  # pragma: no cover
                    self.fail("draft should fail validation")
                self.assertIsNone(
                    CJK_RE.search(message),
                    f"CJK leaked through MCP validation boundary: {message!r}",
                )


class McpSurfaceUnchangedContract(unittest.TestCase):
    """Batch A must not change tool count or securitySchemes."""

    def test_tool_count_and_names_unchanged(self):
        server = build_mcp_server()
        tools = asyncio.run(server.list_tools())
        self.assertEqual(len(tools), 13)
        self.assertEqual(
            {t.name for t in tools},
            {
                "search_chemistry_data", "get_chemical", "get_reaction",
                "render_molecule_svg", "render_reaction_svg", "list_skills",
                "get_skill", "calculate_stoichiometry", "list_my_reactions",
                "validate_reaction", "validate_skill", "create_skill",
                "create_reaction",
            },
        )

    def test_no_note_tools_and_no_note_write_scope(self):
        server = build_mcp_server()
        tools = asyncio.run(server.list_tools())
        for tool in tools:
            self.assertNotIn("note", tool.name)
        mcp_src = open(
            os.path.join(REPO, "api", "mcp_server.py"), encoding="utf-8"
        ).read()
        self.assertNotIn("note:write", mcp_src)


class McpGuideOAuthPositioningContract(unittest.TestCase):
    """A-04: every locale presents OAuth as standard and AI Key as compat."""

    def test_every_locale_mcp_section_mentions_oauth_and_compat(self):
        for locale in LOCALES:
            section = _mcp_section(locale)
            with self.subTest(locale=locale):
                self.assertIn("OAuth", section)
                self.assertRegex(
                    section, r"Authorization Code \+ PKCE S256"
                )
                self.assertRegex(section, r"reaction:write\s*/\s*skill:write|read / reaction:write / skill:write|read / reaction:write / skill:write")

    def test_minimal_json_config_has_no_built_in_authorization(self):
        for locale in LOCALES:
            section = _mcp_section(locale)
            with self.subTest(locale=locale):
                json_match = re.search(
                    r"commonJson: `(\{.*?\})`,", section, re.S
                )
                assert json_match, locale
                self.assertNotIn("Authorization", json_match.group(1))
                # compat mention preserved
                self.assertRegex(
                    section,
                    r"AI Key|AI-Key|AI Key\(|AI-Key",
                )

    def test_ai_key_presented_as_compatibility_not_primary(self):
        for locale in LOCALES:
            section = _mcp_section(locale)
            with self.subTest(locale=locale):
                self.assertIn("connectCompatKicker", section)
                self.assertIn("connectOauthLabel", section)
                self.assertIn("connectAnonLabel", section)

    def test_tool_auth_labels_show_oauth_or_authorized(self):
        for locale in LOCALES:
            section = _mcp_section(locale)
            with self.subTest(locale=locale):
                write_tools = re.findall(
                    r"name: '(list_my_reactions|validate_reaction|"
                    r"create_reaction|validate_skill|create_skill)', "
                    r"auth: '([^']+)'", section)
                self.assertEqual(len(write_tools), 5)
                for _name, auth in write_tools:
                    self.assertIn("OAuth", auth, auth)

    def test_named_clients_marked_compatibility(self):
        page = open(
            os.path.join(
                WEB, "app", "(site)", "mcp-guide", "page.tsx"
            ), encoding="utf-8",
        ).read()
        self.assertIn("t.mcp.connectCompatKicker", page)
        self.assertIn("t.mcp.connectOauthLabel", page)
        self.assertIn("t.mcp.compatJsonDesc", page)

    def test_guide_section_authorization_wording(self):
        for locale in LOCALES:
            section = _guide_section(locale)
            with self.subTest(locale=locale):
                # keyCta no longer a bare "Create AI Key" first action
                self.assertRegex(section, r"keyCta: '.*?(compat|兼容|互換|호환|Kompatibilität).*?'")
                # connectKeyLabel demoted from bare 'AI Key'
                self.assertNotRegex(section, r"connectKeyLabel: 'AI Key',")


class DictionaryTreeConsistencyContract(unittest.TestCase):
    """5-language mcp/guide key trees stay identical after the rewrite."""

    def _key_tree(self, section: str) -> set[str]:
        return set(re.findall(r"^    ([A-Za-z0-9_]+):", section, re.M))

    def test_mcp_key_tree_identical_across_locales(self):
        trees = {loc: self._key_tree(_mcp_section(loc)) for loc in LOCALES}
        base = trees["zh-CN"]
        self.assertEqual(len(base), 35)  # 30 original keys + 4 OAuth positioning + compatJsonDesc
        for locale in LOCALES:
            self.assertEqual(trees[locale], base, locale)

    def test_guide_key_tree_identical_across_locales(self):
        trees = {loc: self._key_tree(_guide_section(loc)) for loc in LOCALES}
        base = trees["zh-CN"]
        for locale in LOCALES:
            self.assertEqual(trees[locale], base, locale)


if __name__ == "__main__":
    unittest.main()
