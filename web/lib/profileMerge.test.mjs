/* 资料设置页迟到 GET 的按字段合并(ZX): 纯 ESM, 不在 tsconfig include 内, 不参与构建。
   运行: cd web && node --test --experimental-strip-types lib/profileMerge.test.mjs */
import test from "node:test";
import assert from "node:assert/strict";
import { mergeLateProfile } from "./profileMerge.ts";

const EMPTY = {
  display_name: "", bio: "", email: "", location: "",
  institution: "", title: "", website: "", orcid: "",
};

test("GET 在途只改名字: 未改字段回填, 改过字段保留当前输入", () => {
  // GET 在途, 用户只改了 display_name
  const current = { ...EMPTY, display_name: "新名字" };
  const incoming = {
    display_name: "旧名字", bio: "服务端 bio", email: "a@b.co",
    location: "上海", institution: "华工社", title: "研究员",
    website: "https://example.com", orcid: "0000-0002-1825-0097",
  };
  const merged = mergeLateProfile(current, incoming, new Set(["display_name"]));
  assert.equal(merged.display_name, "新名字", "用户改过的字段保留当前输入");
  assert.equal(merged.bio, "服务端 bio", "未改字段必须回填(GET 返回后不为空)");
  assert.equal(merged.email, "a@b.co");
  assert.equal(merged.location, "上海");
  assert.equal(merged.institution, "华工社");
  assert.equal(merged.orcid, "0000-0002-1825-0097");
});

test("保存负载即合并结果: bio 等字段不为空串(不清空服务端资料)", () => {
  const current = { ...EMPTY, display_name: "只改了名字" };
  const incoming = { bio: "既有简介", email: "a@b.co" };
  const saved = mergeLateProfile(current, incoming, new Set(["display_name"]));
  assert.equal(saved.bio, "既有简介", "保存时 bio 不得为空");
  assert.equal(saved.email, "a@b.co");
});

test("GET 先到后未编辑: 全量回填(与旧初值行为一致)", () => {
  const merged = mergeLateProfile(
    EMPTY,
    { display_name: "DN", bio: "B" },
    new Set(),
  );
  assert.equal(merged.display_name, "DN");
  assert.equal(merged.bio, "B");
});

test("GET 字段缺失/非字符串归一为空串, 不抛错", () => {
  const merged = mergeLateProfile(EMPTY, { bio: null, email: 42 }, new Set());
  assert.equal(merged.bio, "");
  assert.equal(merged.email, "");
});
