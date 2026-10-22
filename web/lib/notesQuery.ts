/**
 * 工作台笔记列表的查询参数与保存落点 —— 页面 URL、SSR 预取与客户端刷新
 * 共用这一份实现，首屏与刷新天然一致。
 *
 * 实体筛选只有一个身份：chemical 与 reaction 同时出现时 chemical 优先。
 * 页面 URL 用 chemical / reaction，API 用 chemical_id / reaction_id，一一对应。
 */

import type { NoteItem, NoteVisibility } from "./api";

/** 页面 URL 的实体筛选参数（chemical 优先）。 */
export function filterParams(chemicalId?: number, reactionId?: number): URLSearchParams {
  const params = new URLSearchParams();
  if (chemicalId != null) params.set("chemical", String(chemicalId));
  else if (reactionId != null) params.set("reaction", String(reactionId));
  return params;
}

/** 列表页 URL 参数：默认值（visibility=all、page=1）不写进 URL。 */
export function listParams(visibility: NoteVisibility, chemicalId?: number, reactionId?: number, page = 1): URLSearchParams {
  const params = filterParams(chemicalId, reactionId);
  if (visibility !== "all") params.set("visibility", visibility);
  if (page > 1) params.set("page", String(page));
  return params;
}

/** 列表 API 查询串：visibility / page / page_size 恒在。 */
export function apiListQuery(visibility: NoteVisibility, chemicalId?: number, reactionId?: number, page = 1): string {
  const params = new URLSearchParams();
  params.set("visibility", visibility);
  const filter = filterParams(chemicalId, reactionId);
  if (filter.has("chemical")) params.set("chemical_id", filter.get("chemical")!);
  else if (filter.has("reaction")) params.set("reaction_id", filter.get("reaction")!);
  params.set("page", String(page));
  params.set("page_size", "20");
  return params.toString();
}

export type NoteListView = {
  visibility: NoteVisibility;
  page: number;
  chemicalId?: number;
  reactionId?: number;
};

export type SavedNoteRefs = Pick<NoteItem, "visibility" | "chemical_ids" | "reaction_ids">;

/** 刚保存的笔记能否出现在当前列表视图里（第 1 页、可见性与实体筛选都匹配）。 */
export function savedNoteFitsView(view: NoteListView, saved: SavedNoteRefs): boolean {
  if (view.page !== 1) return false;
  if (view.visibility !== "all" && view.visibility !== saved.visibility) return false;
  if (view.chemicalId != null) return saved.chemical_ids.includes(view.chemicalId);
  if (view.reactionId != null) return saved.reaction_ids.includes(view.reactionId);
  return true;
}

/**
 * 保存后跳转的列表 URL 参数：第 1 页、可见性取笔记自身的可见性；
 * 笔记仍引用当前筛选实体时保留筛选，否则去掉 —— 落点列表必须真能显示这条笔记。
 */
export function savedNoteLandingParams(view: NoteListView, saved: SavedNoteRefs): URLSearchParams {
  const params = new URLSearchParams({ tab: "notes" });
  params.set("visibility", saved.visibility);
  if (view.chemicalId != null) {
    if (saved.chemical_ids.includes(view.chemicalId)) params.set("chemical", String(view.chemicalId));
  } else if (view.reactionId != null && saved.reaction_ids.includes(view.reactionId)) {
    params.set("reaction", String(view.reactionId));
  }
  return params;
}
