from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path
from urllib.parse import urlparse


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "huagongshe"

EXPECTED_TOOLS = {
    "search_chemistry_data",
    "get_chemical",
    "get_reaction",
    "render_molecule_svg",
    "render_reaction_svg",
    "list_skills",
    "get_skill",
    "calculate_stoichiometry",
    "list_my_reactions",
    "validate_reaction",
    "create_reaction",
    "validate_skill",
    "create_skill",
}


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _png_size(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise AssertionError(f"{path} is not a PNG with IHDR")
    return struct.unpack(">II", raw[16:24])


class OpenAIPluginPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = _load_json(PLUGIN / "plugin.json")
        cls.mcp = _load_json(PLUGIN / "mcp.json")
        cls.ext = cls.manifest["extensions"]["com.openai"]
        cls.interface = cls.ext["interface"]

    def test_portable_package_identity_and_remote_mcp(self):
        self.assertEqual(
            self.manifest["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        self.assertEqual(self.manifest["name"], "huagongshe-aichem")
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(
            self.mcp["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
        )
        self.assertEqual(set(self.mcp["mcpServers"]), {"huagongshe"})
        server = self.mcp["mcpServers"]["huagongshe"]
        self.assertEqual(server["type"], "streamable-http")
        self.assertEqual(server["url"], "https://huagongshe.com/mcp")

    def test_listing_limits_and_public_urls(self):
        self.assertLessEqual(len(self.interface["displayName"]), 30)
        self.assertLessEqual(len(self.interface["shortDescription"]), 30)
        self.assertLessEqual(len(self.interface["longDescription"]), 4000)
        self.assertLessEqual(len(self.interface["developerName"]), 80)
        self.assertEqual(self.interface["category"], "Education & Research")
        prompts = self.interface["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        self.assertEqual(len(prompts), len(set(prompts)))
        for prompt in prompts:
            self.assertLessEqual(len(prompt), 128)
            self.assertNotIn("@", prompt)
            self.assertNotIn("\n", prompt)
        for key in ("websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"):
            parsed = urlparse(self.interface[key])
            self.assertEqual(parsed.scheme, "https", key)
            self.assertEqual(parsed.netloc, "huagongshe.com", key)

    def test_icons_are_packaged_square_pngs(self):
        for field in ("logo", "composerIcon"):
            rel = self.interface[field]
            self.assertTrue(rel.startswith("./assets/"))
            path = PLUGIN / rel.removeprefix("./")
            self.assertTrue(path.is_file(), field)
            width, height = _png_size(path)
            self.assertEqual(width, height, field)
            self.assertGreaterEqual(width, 48, field)
            self.assertLessEqual(width, 4096, field)
            self.assertLessEqual(path.stat().st_size, 5 * 1024 * 1024, field)

    def test_review_cases_are_complete_and_reference_only_frozen_tools(self):
        cases = self.ext["review"]["test_cases"]
        self.assertEqual(len(cases["positive"]), 5)
        self.assertEqual(len(cases["negative"]), 3)
        for case in cases["positive"]:
            self.assertTrue(case["description"].strip())
            self.assertTrue(case["prompt"].strip())
            self.assertTrue(case["expected_behavior"].strip())
            tools = {name.strip() for name in case["tools_triggered"].split(",")}
            self.assertTrue(tools)
            self.assertTrue(tools <= EXPECTED_TOOLS, tools - EXPECTED_TOOLS)
        for case in cases["negative"]:
            self.assertTrue(case["description"].strip())
            self.assertTrue(case["prompt"].strip())
            self.assertTrue(case["expected_behavior"].strip())

    def test_package_contains_no_credentials_or_fake_submission_artifacts(self):
        keys = {key.lower() for key in _walk_keys(self.manifest)}
        for banned in (
            "test_credentials", "reviewer_credentials", "reviewer_instructions",
            "client_secret", "access_token", "refresh_token",
        ):
            self.assertNotIn(banned, keys)
        self.assertNotIn("demo_recording_url", keys)
        self.assertNotIn("screenshots", self.interface)
        serialized = json.dumps(self.manifest).lower()
        self.assertNotIn("note:write", serialized)

    def test_public_submission_pages_and_domain_challenge_exist(self):
        for name in ("privacy", "terms", "support"):
            page = REPO / "web" / "app" / "(site)" / name / "page.tsx"
            self.assertTrue(page.is_file(), name)
            self.assertIn("mail@huagongshe.com", page.read_text(encoding="utf-8"))
        challenge = (
            REPO / "web" / "app" / ".well-known" / "openai-apps-challenge" / "route.ts"
        ).read_text(encoding="utf-8")
        self.assertIn("HGS_OPENAI_APPS_CHALLENGE", challenge)
        self.assertIn('"cache-control": "no-store"', challenge)
        self.assertNotIn("openai-apps-challenge=", challenge)

    def test_public_docs_describe_mixed_oauth_without_expanding_rest_bearer(self):
        llms = (REPO / "web" / "public" / "llms.txt").read_text(encoding="utf-8")
        self.assertIn("OAuth", llms)
        self.assertIn("reaction:write", llms)
        self.assertIn("skill:write", llms)
        self.assertIn("HTTP API", llms)
        self.assertIn("AI Key", llms)


if __name__ == "__main__":
    unittest.main()
