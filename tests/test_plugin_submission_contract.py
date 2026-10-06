"""Submission-package contract for the HGS AIchem public plugin."""

from __future__ import annotations

import json
import struct
import unittest
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
FROZEN_TOOLS = {
    "search_chemistry_data", "get_chemical", "get_reaction",
    "render_molecule_svg", "render_reaction_svg", "list_skills",
    "get_skill", "calculate_stoichiometry", "list_my_reactions",
    "validate_reaction", "validate_skill", "create_skill", "create_reaction",
}


class PluginSubmissionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((PLUGIN / "plugin.json").read_text("utf-8"))
        cls.mcp = json.loads((PLUGIN / "mcp.json").read_text("utf-8"))
        cls.openai = cls.manifest["extensions"]["com.openai"]
        cls.interface = cls.openai["interface"]

    def test_portable_package_has_one_production_mcp(self):
        self.assertEqual(
            self.manifest["$schema"],
            "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        )
        servers = self.mcp["mcpServers"]
        self.assertEqual(set(servers), {"hgs_aichem"})
        self.assertEqual(servers["hgs_aichem"]["type"], "streamable-http")
        self.assertEqual(servers["hgs_aichem"]["url"], "https://huagongshe.com/mcp")
        self.assertFalse((PLUGIN / ".app.json").exists())
        self.assertNotIn("apps", self.openai)
        self.assertNotIn("hooks", self.openai)

    def test_listing_limits_and_public_urls(self):
        self.assertLessEqual(len(self.interface["displayName"]), 30)
        self.assertLessEqual(len(self.interface["shortDescription"]), 30)
        self.assertLessEqual(len(self.interface["longDescription"]), 4000)
        self.assertLessEqual(len(self.interface["developerName"]), 80)
        self.assertLessEqual(len(self.interface["defaultPrompt"]), 3)
        for prompt in self.interface["defaultPrompt"]:
            self.assertLessEqual(len(prompt), 128)
            self.assertNotIn("@", prompt)
        for key in (
            "websiteURL", "supportURL", "privacyPolicyURL", "termsOfServiceURL"
        ):
            parsed = urlparse(self.interface[key])
            self.assertEqual(parsed.scheme, "https")
            self.assertEqual(parsed.netloc, "huagongshe.com")

    def test_directory_category_brand_and_icon_constraints(self):
        self.assertIn(
            self.interface["category"],
            {
                "Productivity", "Creativity", "Developer Tools",
                "Business & Operations", "Data & Analytics", "Communication",
                "Education & Research", "Security", "Finance", "Healthcare",
                "Travel", "Entertainment", "Other",
            },
        )

        color = self.interface["brandColor"]
        self.assertRegex(color, r"^#[0-9A-Fa-f]{6}$")
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))

        def linear(channel):
            value = channel / 255
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

        luminance = (
            0.2126 * linear(rgb[0])
            + 0.7152 * linear(rgb[1])
            + 0.0722 * linear(rgb[2])
        )
        contrast_on_white = 1.05 / (luminance + 0.05)
        self.assertGreaterEqual(contrast_on_white, 2.0)

        for key in ("logo", "composerIcon"):
            path = PLUGIN / self.interface[key][2:]
            raw = path.read_bytes()
            self.assertLessEqual(len(raw), 5 * 1024 * 1024)
            self.assertTrue(raw.startswith(b"\x89PNG\r\n\x1a\n"))
            width, height = struct.unpack(">II", raw[16:24])
            self.assertEqual(width, height)
            self.assertGreaterEqual(width, 48)
            self.assertLessEqual(width, 4096)

    def test_review_case_counts_and_tool_names(self):
        cases = self.openai["review"]["test_cases"]
        self.assertEqual(len(cases["positive"]), 5)
        self.assertEqual(len(cases["negative"]), 3)
        for case in cases["positive"]:
            tools = {
                value.strip()
                for value in case["tools_triggered"].split(",")
                if value.strip()
            }
            self.assertTrue(tools)
            self.assertTrue(tools <= FROZEN_TOOLS)
            self.assertTrue(case["expected_behavior"].strip())

    def test_no_unimplemented_note_plugin_claims(self):
        payload = json.dumps(self.manifest, ensure_ascii=False).lower()
        self.assertNotIn("note:write", payload)
        self.assertNotIn("create_note", payload)
        self.assertNotIn("list_notes", payload)

    def test_primary_icon_is_packaged_and_no_screenshots_without_mcp_ui(self):
        for key in ("logo", "composerIcon"):
            value = self.interface[key]
            self.assertTrue(value.startswith("./"))
            self.assertTrue((PLUGIN / value[2:]).is_file())
        self.assertNotIn("screenshots", self.interface)

    def test_demo_recording_is_not_faked(self):
        # A real reviewer-accessible recording is a portal prerequisite.
        self.assertNotIn("demo_recording_url", self.openai["review"])


if __name__ == "__main__":
    unittest.main()
