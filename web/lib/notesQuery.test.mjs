import assert from "node:assert/strict";
import { test } from "node:test";

/**
 * 工作台笔记列表查询参数与保存落点：直接测 lib/notesQuery.ts 真实实现
 * （NotesPanel 客户端刷新与 aichem 页 SSR 预取共用这一份）。
 */
const {
  filterParams, listParams, apiListQuery, savedNoteFitsView, savedNoteLandingParams,
} = await import("./notesQuery.ts");

const qs = (params) => params.toString();

test("页面 URL 用 chemical / reaction 参数名，chemical 优先", () => {
  assert.equal(qs(listParams("all", 7)), "chemical=7");
  assert.equal(qs(listParams("all", undefined, 9)), "reaction=9");
  assert.equal(qs(listParams("all", 7, 9)), "chemical=7");
  assert.equal(qs(filterParams(7, 9)), "chemical=7");
  assert.equal(qs(filterParams()), "");
});

test("页面 URL 省略默认值，非默认值保留筛选", () => {
  assert.equal(qs(listParams("all")), "");
  assert.equal(qs(listParams("private", 7, undefined, 2)), "chemical=7&visibility=private&page=2");
});

test("API 查询用 chemical_id / reaction_id，visibility / page / page_size 恒在", () => {
  assert.equal(apiListQuery("all", 7), "visibility=all&chemical_id=7&page=1&page_size=20");
  assert.equal(apiListQuery("all", undefined, 9), "visibility=all&reaction_id=9&page=1&page_size=20");
  assert.equal(apiListQuery("all", 7, 9), "visibility=all&chemical_id=7&page=1&page_size=20");
  assert.equal(apiListQuery("private", undefined, undefined, 2), "visibility=private&page=2&page_size=20");
});

const view = (over = {}) => ({ visibility: "all", page: 1, ...over });
const saved = (over = {}) => ({ visibility: "public", chemical_ids: [], reaction_ids: [], ...over });

test("保存的笔记能出现在当前列表时原地刷新", () => {
  assert.equal(savedNoteFitsView(view(), saved()), true);
  assert.equal(savedNoteFitsView(view(), saved({ visibility: "private" })), true);
  assert.equal(savedNoteFitsView(view({ visibility: "private" }), saved({ visibility: "private" })), true);
  assert.equal(savedNoteFitsView(view({ chemicalId: 7 }), saved({ chemical_ids: [7] })), true);
  assert.equal(savedNoteFitsView(view({ reactionId: 456 }), saved({ reaction_ids: [456] })), true);
});

test("保存的笔记不在当前列表里时需要跳转", () => {
  assert.equal(savedNoteFitsView(view({ visibility: "public" }), saved({ visibility: "private" })), false);
  assert.equal(savedNoteFitsView(view({ page: 2 }), saved()), false);
  assert.equal(savedNoteFitsView(view({ chemicalId: 7 }), saved({ chemical_ids: [9] })), false);
  // chemical 筛选优先：只引用了同号反应不算命中
  assert.equal(savedNoteFitsView(view({ chemicalId: 7, reactionId: 9 }), saved({ reaction_ids: [9] })), false);
});

test("跳转落点：可见性取笔记自身，筛选仅在笔记仍引用该实体时保留", () => {
  assert.equal(qs(savedNoteLandingParams(view({ page: 2, chemicalId: 123 }), saved({ visibility: "private" }))),
    "tab=notes&visibility=private");
  assert.equal(qs(savedNoteLandingParams(view({ chemicalId: 123 }), saved({ chemical_ids: [7] }))),
    "tab=notes&visibility=public");
  assert.equal(qs(savedNoteLandingParams(view({ reactionId: 456 }), saved({ chemical_ids: [1], reaction_ids: [9] }))),
    "tab=notes&visibility=public");
  assert.equal(qs(savedNoteLandingParams(view({ page: 2, chemicalId: 123 }), saved({ chemical_ids: [123, 5] }))),
    "tab=notes&visibility=public&chemical=123");
  assert.equal(qs(savedNoteLandingParams(view({ page: 2, reactionId: 456 }), saved({ reaction_ids: [456] }))),
    "tab=notes&visibility=public&reaction=456");
});
