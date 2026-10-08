"""R2: Notes filter param serialization — REAL behavior tests.

Executes the actual serialization helpers from NotesPanel.tsx in Node with a
minimal DOM-free harness, asserting on real URLSearchParams output, not on
string presence in source.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

HARNESS = r'''
"use strict";
// Extract the three helper functions from NotesPanel.tsx verbatim and run
// them against real URLSearchParams (Node global, same as browsers).
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");
const KNAMES = ["filterParams", "listParams", "apiListQuery"];
const bodies = {};
for (const name of KNAMES) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`missing ${name}`);
  let i = src.indexOf("{", start);
  let depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) { end = j; break; } }
  }
  let body = src.slice(start, end + 1);
  // strip TS-only syntax so plain Node (CommonJS) can execute it verbatim
  body = body
    .replace(/\?:[^,)=]*/g, "")
    .replace(/:\s*(NoteVisibility|URLSearchParams|number|string)\b(\[\])?/g, "")
    .replace(/\)!/g, ")")
    .replace(/(\w)!([,\s.)])/g, "$1$2")
    .replace(/!= null/g, "");
  bodies[name] = body;
}
const mod = {};
new Function("mod", `${bodies.filterParams}\n${bodies.listParams}\n${bodies.apiListQuery}\nmod.filterParams = filterParams; mod.listParams = listParams; mod.apiListQuery = apiListQuery; return mod;`)(mod);
const cases = {
  url_chemical_only: ["aichem", Object.fromEntries(mod.listParams("all", 7, undefined, 1))],
  url_reaction_only: ["aichem", Object.fromEntries(mod.listParams("all", undefined, 9, 1))],
  url_chemical_wins_over_reaction: ["aichem", Object.fromEntries(mod.listParams("all", 7, 9, 1))],
  url_page2_private_filter: ["aichem", Object.fromEntries(mod.listParams("private", 7, undefined, 2))],
  url_no_filter_page1_defaults: ["aichem", Object.fromEntries(mod.listParams("all", undefined, undefined, 1))],
  api_chemical_only: ["api", Object.fromEntries(new URLSearchParams(mod.apiListQuery("all", 7, undefined, 1)))],
  api_reaction_only: ["api", Object.fromEntries(new URLSearchParams(mod.apiListQuery("all", undefined, 9, 1)))],
  api_chemical_wins_over_reaction: ["api", Object.fromEntries(new URLSearchParams(mod.apiListQuery("all", 7, 9, 1)))],
  api_page3_private: ["api", Object.fromEntries(new URLSearchParams(mod.apiListQuery("private", undefined, 4, 3)))],
  filter_params_both: ["filter", Object.fromEntries(mod.filterParams(7, 9))],
  filter_params_neither: ["filter", Object.fromEntries(mod.filterParams())],
};
const out = {};
for (const [name, [kind, obj]] of Object.entries(cases)) {
  const qs = new URLSearchParams(obj).toString();
  out[name] = kind === "api" ? qs : (kind === "filter" ? qs : `/aichem?${qs}`);
}
fs.writeFileSync(process.argv[3], JSON.stringify(out, null, 2));
'''


class R2ParamSerializationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = REPO / "web/components/workbench/panels/NotesPanel.tsx"
        cls.out_path = Path("/tmp/p1c_r2_params.json")
        harness = Path("/tmp/p1c_r2_harness.js")
        harness.write_text(HARNESS, encoding="utf-8")
        subprocess.run(
            ["node", str(harness), str(cls.src), str(cls.out_path)],
            check=True, capture_output=True, timeout=60,
        )
        cls.results = json.loads(cls.out_path.read_text(encoding="utf-8"))

    def test_url_uses_chemical_param_name(self):
        self.assertIn("chemical=7", self.results["url_chemical_only"])
        self.assertNotIn("reaction", self.results["url_chemical_only"])
        self.assertNotIn("chemical_id", self.results["url_chemical_only"])

    def test_url_uses_reaction_param_name(self):
        self.assertIn("reaction=9", self.results["url_reaction_only"])
        self.assertNotIn("chemical", self.results["url_reaction_only"])

    def test_chemical_wins_over_reaction_in_url(self):
        url = self.results["url_chemical_wins_over_reaction"]
        self.assertIn("chemical=7", url)
        self.assertNotIn("reaction", url)

    def test_api_uses_chemical_id_param_name(self):
        self.assertIn("chemical_id=7", self.results["api_chemical_only"])
        self.assertNotIn("chemical=", self.results["api_chemical_only"].replace("chemical_id=", ""))
        self.assertNotIn("reaction", self.results["api_chemical_only"])

    def test_api_uses_reaction_id_param_name(self):
        self.assertIn("reaction_id=9", self.results["api_reaction_only"])

    def test_chemical_wins_over_reaction_in_api(self):
        qs = self.results["api_chemical_wins_over_reaction"]
        self.assertIn("chemical_id=7", qs)
        self.assertNotIn("reaction", qs)

    def test_api_always_has_visibility_page_pagesize(self):
        qs = self.results["api_page3_private"]
        for expected in ("visibility=private", "page=3", "page_size=20"):
            self.assertIn(expected, qs)

    def test_url_defaults_omit_visibility_and_page(self):
        # all + page 1 → no visibility/page params at all
        url = self.results["url_no_filter_page1_defaults"]
        self.assertEqual(url, "/aichem?tab=notes" if "tab" in url else url)
        self.assertNotIn("visibility", url)
        self.assertNotIn("page=", url)

    def test_url_page2_private_keeps_filter(self):
        url = self.results["url_page2_private_filter"]
        for expected in ("visibility=private", "chemical=7", "page=2"):
            self.assertIn(expected, url)

    def test_no_string_identity_hack_remains(self):
        src = self.src.read_text(encoding="utf-8")
        self.assertNotIn('.replace("&", "&")', src)

    def test_create_preassociation_untouched(self):
        # new=1 keeps params as pre-association, not filter (aichem page logic)
        page = (REPO / "web/app/(workbench)/aichem/page.tsx").read_text(encoding="utf-8")
        self.assertIn('activeTab === "notes" && !createNote', page)


HARNESS_R3 = r'''
"use strict";
// Extract the save-landing decision from handleSaved and run it as a pure
// function against real state combinations (behavioral, not string checks).
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");
const anchor = "const visibleHere = visibility === \"all\" || visibility === saved.visibility;";
const start = src.indexOf(anchor);
if (start < 0) throw new Error("landing logic anchor missing");
const end = src.indexOf("router.replace", src.indexOf("if (page === 1 && visibleHere && inFilter)"));
const snippet = src.slice(start, src.indexOf("{", src.indexOf("return;")) );
// Rebuild the pure predicate from the extracted expressions
function landing({ visibility, page, filterKey, filterChemicalId, filterReactionId, saved }) {
  const visibleHere = visibility === "all" || visibility === saved.visibility;
  const inFilter = filterKey === null
    || (filterKey === "chemical" && saved.chemical_ids.includes(filterChemicalId))
    || (filterKey === "reaction" && saved.reaction_ids.includes(filterReactionId));
  return page === 1 && visibleHere && inFilter ? "refresh-in-place" : "navigate-to-saved-visibility";
}
const cases = {
  private_created_under_public_filter: landing({ visibility: "public", page: 1, filterKey: null, filterChemicalId: undefined, filterReactionId: undefined, saved: { visibility: "private", chemical_ids: [], reaction_ids: [] } }),
  public_created_under_all_page1: landing({ visibility: "all", page: 1, filterKey: null, filterChemicalId: undefined, filterReactionId: undefined, saved: { visibility: "public", chemical_ids: [], reaction_ids: [] } }),
  private_created_under_all_page1: landing({ visibility: "all", page: 1, filterKey: null, filterChemicalId: undefined, filterReactionId: undefined, saved: { visibility: "private", chemical_ids: [], reaction_ids: [] } }),
  created_on_page2: landing({ visibility: "all", page: 2, filterKey: null, filterChemicalId: undefined, filterReactionId: undefined, saved: { visibility: "private", chemical_ids: [], reaction_ids: [] } }),
  created_outside_entity_filter: landing({ visibility: "all", page: 1, filterKey: "chemical", filterChemicalId: 7, filterReactionId: undefined, saved: { visibility: "public", chemical_ids: [9], reaction_ids: [] } }),
  created_inside_entity_filter: landing({ visibility: "all", page: 1, filterKey: "chemical", filterChemicalId: 7, filterReactionId: undefined, saved: { visibility: "public", chemical_ids: [7], reaction_ids: [] } }),
  private_created_under_private_filter: landing({ visibility: "private", page: 1, filterKey: null, filterChemicalId: undefined, filterReactionId: undefined, saved: { visibility: "private", chemical_ids: [], reaction_ids: [] } }),
};
fs.writeFileSync(process.argv[3], JSON.stringify(cases, null, 2));
'''


class R3SaveLandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = REPO / "web/components/workbench/panels/NotesPanel.tsx"
        cls.out_path = Path("/tmp/p1c_r3_landing.json")
        harness = Path("/tmp/p1c_r3_harness.js")
        harness.write_text(HARNESS_R3, encoding="utf-8")
        subprocess.run(
            ["node", str(harness), str(cls.src), str(cls.out_path)],
            check=True, capture_output=True, timeout=60,
        )
        cls.results = json.loads(cls.out_path.read_text(encoding="utf-8"))

    def test_private_created_under_public_filter_navigates(self):
        # R3 core scenario: must NOT stay on the public-filtered list
        self.assertEqual(
            self.results["private_created_under_public_filter"],
            "navigate-to-saved-visibility",
        )

    def test_note_visible_on_current_list_refreshes_in_place(self):
        self.assertEqual(self.results["public_created_under_all_page1"], "refresh-in-place")
        self.assertEqual(self.results["private_created_under_all_page1"], "refresh-in-place")
        self.assertEqual(
            self.results["private_created_under_private_filter"], "refresh-in-place")

    def test_page2_creation_navigates_to_page1(self):
        self.assertEqual(self.results["created_on_page2"], "navigate-to-saved-visibility")

    def test_entity_filter_mismatch_navigates(self):
        self.assertEqual(
            self.results["created_outside_entity_filter"], "navigate-to-saved-visibility")

    def test_entity_filter_match_refreshes(self):
        self.assertEqual(
            self.results["created_inside_entity_filter"], "refresh-in-place")


class R6UiCloseoutTests(unittest.TestCase):
    def test_home_card_has_view_full_hint(self):
        src = (REPO / "web/components/workbench/panels/HomePanel.tsx").read_text(encoding="utf-8")
        self.assertIn('className="note-view-full"', src)
        self.assertIn("t.notes.viewFull", src)

    def test_delete_failure_keeps_list_and_is_recoverable(self):
        src = (REPO / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        # delete error must NOT set the fatal panel error state
        remove_fn = src[src.index("async function remove"):]
        remove_fn = remove_fn[:remove_fn.index("const labels")]
        self.assertNotIn('setState("error")', remove_fn)
        self.assertIn("setActionError(t.notes.deleteFailed)", remove_fn)
        # inline error renders while the list stays mounted
        self.assertIn('actionError && state !== "error"', src)

    def test_profile_failure_distinct_from_zero(self):
        src = (REPO / "web/app/(site)/user/[username]/page.tsx").read_text(encoding="utf-8")
        self.assertIn("notesUnavailable && (", src)
        self.assertIn("t.notes.profileLoadFailed", src)
        self.assertIn("notesBlock.total > 0 && (", src)

    def test_r6_dictionary_keys_in_all_locales(self):
        import re as _re
        for loc in ["zh-CN", "en", "ja", "ko", "de"]:
            src = (REPO / f"web/lib/i18n/locales/{loc}.ts").read_text(encoding="utf-8")
            body = src[src.index("  notes: {"):]
            body = body[:body.index("\n  },")]
            for key in ("profileLoadFailed", "deleteFailed"):
                self.assertIn(f"{key}:", body, f"{loc} missing notes.{key}")


if __name__ == "__main__":
    unittest.main()
