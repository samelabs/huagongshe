import assert from "node:assert/strict";
import { test } from "node:test";

/**
 * 笔记列表呈现派生单测：列表不造模板标题——
 * 多行短首行 → 首行作标题；其余情况 → 无标题、正文即主文本；
 * 关联实体不参与（由行内徽标表达）；空内容无文本。
 */
const { noteListPresentation } = await import("./noteHeadline.ts");

test("单行笔记：无标题，正文即主文本", () => {
  const pres = noteListPresentation({ content: "茶多酚在碱性条件下易氧化，存放时注意避光隔热。" });
  assert.equal(pres.title, null);
  assert.equal(pres.body, "茶多酚在碱性条件下易氧化，存放时注意避光隔热。");
});

test("多行且首行不超过 60 字：首行作标题，其余作摘要", () => {
  const pres = noteListPresentation({ content: "阿司匹林合成要点\n水杨酸 + 乙酸酐，82 °C 水浴 1 小时，收率约 78%。\n冷却后析出晶体。" });
  assert.equal(pres.title, "阿司匹林合成要点");
  assert.equal(pres.body, "水杨酸 + 乙酸酐，82 °C 水浴 1 小时，收率约 78%。\n冷却后析出晶体。");
});

test("多行但首行超过 60 字：无标题，整段作主文本", () => {
  const longFirst = "长".repeat(61);
  const pres = noteListPresentation({ content: `${longFirst}\n第二行内容。` });
  assert.equal(pres.title, null);
  assert.equal(pres.body, `${longFirst}\n第二行内容。`);
});

test("空内容：无标题也无正文", () => {
  const pres = noteListPresentation({ content: "" });
  assert.equal(pres.title, null);
  assert.equal(pres.body, "");
  const blank = noteListPresentation({ content: "  \n  \n" });
  assert.equal(blank.title, null);
  assert.equal(blank.body, "");
});

test("关联实体不影响派生（实体由行内徽标表达，不进标题）", () => {
  const content = "单行笔记内容。";
  const without = noteListPresentation({ content });
  const withEntities = noteListPresentation({
    content,
    chemical_ids: [10, 11],
    reaction_ids: [3],
    username: "hgs_demo",
    display_name: "SUN Demo",
  });
  assert.deepEqual(withEntities, without);
});

test("首行前后有空行时以首个非空行为准", () => {
  const pres = noteListPresentation({ content: "\n\n  标题行  \n正文行。" });
  assert.equal(pres.title, "标题行");
  assert.equal(pres.body, "正文行。");
});
