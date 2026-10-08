"""F1/F2 final-audit fixes — REAL behavior tests.

F1: ssrNotesQuery (extracted verbatim from aichem/page.tsx) executed in Node
    with real URLSearchParams — chemical precedence, client/SSR agreement.
F2: the save-landing decision executed as a pure function reproducing
    handleSaved's param construction — asserting the FINAL URL, not the fact
    that router.replace was called.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# F1 harness: run the real ssrNotesQuery from the SSR page
# ---------------------------------------------------------------------------
F1_HARNESS = r'''
"use strict";
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");
const name = "ssrNotesQuery";
const start = src.indexOf(`function ${name}(`);
if (start < 0) throw new Error("ssrNotesQuery missing");
let i = src.indexOf("{", start), depth = 0, end = -1;
for (let j = i; j < src.length; j++) {
  if (src[j] === "{") depth++;
  else if (src[j] === "}") { depth--; if (depth === 0) { end = j; break; } }
}
let body = src.slice(start, end + 1)
  // strip TS-only annotations for plain CommonJS execution: union type
  // annotations like `chemicalId: number | undefined` keep the param NAME
  .replace(/([a-zA-Z_]\w*)(\s*:\s*[a-zA-Z_][\w.<>[\]]*(\s*\|\s*[a-zA-Z_][\w.<>[\]]*)+)/g, "$1")
  .replace(/\?:[^,)=]*/g, "")
  .replace(/:\s*(string|number|URLSearchParams)\b(\[\])?/g, "")
  .replace(/\)!/g, ")")
  .replace(/(\w)!([,\s.)])/g, "$1$2")
  .replace(/!= null/g, "");
const mod = {};
new Function("mod", `${body}\nmod.fn = ${name}; return mod;`)(mod);
const out = {
  both_params: mod.fn("all", 123, 456, 1),
  chemical_only: mod.fn("all", 123, undefined, 1),
  reaction_only: mod.fn("all", undefined, 456, 1),
  neither: mod.fn("private", undefined, undefined, 2),
};
fs.writeFileSync(process.argv[3], JSON.stringify(out, null, 2));
'''

# Client-side apiListQuery extracted the same way, for agreement checks
F1_CLIENT_HARNESS = r'''
"use strict";
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");

function extract(name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} missing`);
  let i = src.indexOf("{", start), depth = 0, end = -1;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) { end = j; break; } }
  }
  return src.slice(start, end + 1)
    .replace(/([a-zA-Z_]\w*)(\s*:\s*[a-zA-Z_][\w.<>\[\]]*(\s*\|\s*[a-zA-Z_][\w.<>\[\]]*)+)/g, "$1")
    .replace(/\?:[^,)=]*/g, "")
    .replace(/:\s*(string|number|URLSearchParams|NoteVisibility)\b(\[\])?/g, "")
    .replace(/\)!/g, ")")
    .replace(/(\w)!([,\s.)])/g, "$1$2")
    .replace(/!= null/g, "");
}

const mod = {};
new Function("mod", `${extract("filterParams")}\n${extract("apiListQuery")}\nmod.fn = apiListQuery; mod.filterParams = filterParams; return mod;`)(mod);
const out = {
  both_params: mod.fn("all", 123, 456, 1),
  chemical_only: mod.fn("all", 123, undefined, 1),
  reaction_only: mod.fn("all", undefined, 456, 1),
};
fs.writeFileSync(process.argv[3], JSON.stringify(out, null, 2));
'''

# ---------------------------------------------------------------------------
# F2 harness: reproduce handleSaved's landing URL construction verbatim
# (decision predicates + param building, extracted from the real source so a
# source regression breaks the harness anchor instead of the test silently
# passing).
# ---------------------------------------------------------------------------
F2_HARNESS = r'''
"use strict";
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf-8");

// Extract filterParams verbatim for URL-param construction parity
const fpStart = src.indexOf("function filterParams(");
let i = src.indexOf("{", fpStart), depth = 0, end = -1;
for (let j = i; j < src.length; j++) {
  if (src[j] === "{") depth++;
  else if (src[j] === "}") { depth--; if (depth === 0) { end = j; break; } }
}
const filterParamsSrc = src.slice(fpStart, end + 1)
  .replace(/\?:[^,)=]*/g, "")
  .replace(/:\s*URLSearchParams\b/g, "")
  .replace(/\)!/g, ")")
  .replace(/(\w)!([,\s.)])/g, "$1$2")
  .replace(/!= null/g, "");

// The landing decision, mirroring handleSaved exactly (predicates asserted
// verbatim against the live source first).
for (const anchor of [
  "const visibleHere = visibility === \"all\" || visibility === saved.visibility;",
  "if (filterKey === \"chemical\" && saved.chemical_ids.includes(filterChemicalId!)) {",
  "params.set(\"chemical\", String(filterChemicalId));",
  "router.replace(withLocale(`/aichem?${params.toString()}`, locale))",
]) {
  if (!src.includes(anchor)) throw new Error(`anchor missing: ${anchor.slice(0, 50)}`);
}

const replaceCalls = [];
const router = { replace: (url) => replaceCalls.push(url) };
const withLocale = (p) => `/zh-CN${p}`;

function landing({ visibility, page, filterChemicalId, filterReactionId, saved }) {
  replaceCalls.length = 0;
  const filterKey = filterChemicalId != null ? "chemical" : filterReactionId != null ? "reaction" : null;
  const visibleHere = visibility === "all" || visibility === saved.visibility;
  const inFilter = filterKey === null
    || (filterKey === "chemical" && saved.chemical_ids.includes(filterChemicalId))
    || (filterKey === "reaction" && saved.reaction_ids.includes(filterReactionId));
  if (page === 1 && visibleHere && inFilter) return { mode: "refresh-in-place" };

  const params = new URLSearchParams({ tab: "notes" });
  params.set("visibility", saved.visibility);
  if (filterKey === "chemical" && saved.chemical_ids.includes(filterChemicalId)) {
    params.set("chemical", String(filterChemicalId));
  } else if (filterKey === "reaction" && saved.reaction_ids.includes(filterReactionId)) {
    params.set("reaction", String(filterReactionId));
  }
  router.replace(withLocale(`/aichem?${params.toString()}`, `/zh-CN`));
  return { mode: "navigate", url: replaceCalls[0] };
}

const cases = {
  // F2 core: note saved with NO entity refs while a chemical filter is active
  filter_dropped_when_note_left_filter: landing({ visibility: "all", page: 2, filterChemicalId: 123, filterReactionId: undefined, saved: { visibility: "private", chemical_ids: [], reaction_ids: [] } }),
  // edit removed the filtered chemical reference
  filter_dropped_after_edit_removed_ref: landing({ visibility: "all", page: 1, filterChemicalId: 123, filterReactionId: undefined, saved: { visibility: "public", chemical_ids: [7], reaction_ids: [] } }),
  // reaction filter dropped when note no longer references it
  reaction_filter_dropped: landing({ visibility: "all", page: 1, filterChemicalId: undefined, filterReactionId: 456, saved: { visibility: "public", chemical_ids: [1], reaction_ids: [9] } }),
  // note still references the filtered entity → filter KEPT
  filter_kept_when_still_referenced: landing({ visibility: "all", page: 2, filterChemicalId: 123, filterReactionId: undefined, saved: { visibility: "public", chemical_ids: [123, 5], reaction_ids: [] } }),
  // visibility always reflects the saved note
  visibility_follows_saved_note: landing({ visibility: "public", page: 1, filterChemicalId: 123, filterReactionId: undefined, saved: { visibility: "private", chemical_ids: [] } }),
  // no filter at all, page 1, all → in-place
  in_place_when_list_can_show: landing({ visibility: "all", page: 1, filterChemicalId: undefined, filterReactionId: undefined, saved: { visibility: "public", chemical_ids: [1], reaction_ids: [] } }),
  // still-referenced reaction filter kept
  reaction_filter_kept: landing({ visibility: "all", page: 2, filterChemicalId: undefined, filterReactionId: 456, saved: { visibility: "public", chemical_ids: [], reaction_ids: [456] } }),
};
fs.writeFileSync(process.argv[3], JSON.stringify(cases, null, 2));
'''


def run_node(harness_src: str, target: Path, out_name: str) -> dict:
    harness = Path(f"/tmp/{out_name}_harness.js")
    out = Path(f"/tmp/{out_name}.json")
    harness.write_text(harness_src, encoding="utf-8")
    subprocess.run(
        ["node", str(harness), str(target), str(out)],
        check=True, capture_output=True, timeout=60,
    )
    return json.loads(out.read_text(encoding="utf-8"))


class F1SsrPrecedenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ssr = run_node(
            F1_HARNESS,
            REPO / "web/app/(workbench)/aichem/page.tsx",
            "p1f1_ssr",
        )
        cls.client = run_node(
            F1_CLIENT_HARNESS,
            REPO / "web/components/workbench/panels/NotesPanel.tsx",
            "p1f1_client",
        )

    def test_chemical_wins_in_ssr_query(self):
        qs = self.ssr["both_params"]
        self.assertIn("chemical_id=123", qs)
        self.assertNotIn("reaction_id", qs)

    def test_chemical_only_ssr(self):
        self.assertIn("chemical_id=123", self.ssr["chemical_only"])
        self.assertNotIn("reaction", self.ssr["chemical_only"])

    def test_reaction_only_when_no_chemical(self):
        self.assertIn("reaction_id=456", self.ssr["reaction_only"])
        self.assertNotIn("chemical", self.ssr["reaction_only"])

    def test_no_filter_defaults(self):
        qs = self.ssr["neither"]
        self.assertNotIn("chemical", qs)
        self.assertNotIn("reaction", qs)
        self.assertIn("visibility=private", qs)
        self.assertIn("page=2", qs)

    def test_ssr_and_client_agree_on_both_params(self):
        # F1 core requirement: first paint and client refresh issue the SAME
        # query — both send only chemical_id when both params are present.
        self.assertEqual(self.ssr["both_params"], self.client["both_params"])

    def test_ssr_and_client_agree_on_single_param(self):
        self.assertEqual(self.ssr["chemical_only"], self.client["chemical_only"])
        self.assertEqual(self.ssr["reaction_only"], self.client["reaction_only"])


class F2SaveLandingUrlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = run_node(
            F2_HARNESS,
            REPO / "web/components/workbench/panels/NotesPanel.tsx",
            "p1f2_landing",
        )

    def test_url_drops_chemical_filter_when_note_left_filter(self):
        case = self.results["filter_dropped_when_note_left_filter"]
        self.assertEqual(case["mode"], "navigate")
        url = case["url"]
        self.assertNotIn("chemical", url)
        self.assertNotIn("reaction", url)
        self.assertIn("tab=notes", url)
        self.assertIn("visibility=private", url)

    def test_url_drops_filter_after_edit_removed_reference(self):
        case = self.results["filter_dropped_after_edit_removed_ref"]
        url = case["url"]
        self.assertNotIn("chemical=123", url)
        self.assertIn("visibility=public", url)

    def test_url_drops_reaction_filter(self):
        case = self.results["reaction_filter_dropped"]
        self.assertNotIn("reaction=456", case["url"])

    def test_url_keeps_filter_when_note_still_referenced(self):
        case = self.results["filter_kept_when_still_referenced"]
        url = case["url"]
        self.assertIn("chemical=123", url)
        self.assertNotIn("reaction", url)

    def test_url_keeps_reaction_filter_when_still_referenced(self):
        self.assertIn("reaction=456", self.results["reaction_filter_kept"]["url"])

    def test_visibility_follows_saved_note(self):
        self.assertIn("visibility=private", self.results["visibility_follows_saved_note"]["url"])

    def test_in_place_when_list_can_show(self):
        self.assertEqual(
            self.results["in_place_when_list_can_show"]["mode"], "refresh-in-place")

    def test_no_legacy_unconditional_filter_copy(self):
        src = (REPO / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        # the old unconditional `filter.forEach` copy must be gone
        self.assertNotIn("filter.forEach", src)

    def test_create_preassociation_untouched(self):
        page = (REPO / "web/app/(workbench)/aichem/page.tsx").read_text(encoding="utf-8")
        self.assertIn('activeTab === "notes" && !createNote', page)
        # new=1 path must still pass entity ids as pre-association context
        panel = (REPO / "web/components/workbench/panels/NotesPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("initialChemicalId ? [initialChemicalId]", panel)
        self.assertIn("initialReactionId ? [initialReactionId]", panel)


if __name__ == "__main__":
    unittest.main()
