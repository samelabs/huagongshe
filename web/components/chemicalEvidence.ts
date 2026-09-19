/** E9-B: presentation-only helper(数据组合已下沉后端 chemical_semantic)。
 *
 * 只保留 disclosure 判定: 短列表(≤2 值且每值 ≤160 字)直接可见, 长列表默认折叠。
 * evidenceEntries/evidenceSectionKeys 等组合职责已随 semantic 后端化删除。
 */

export type EvidenceEntry = { label: string; values: string[] };

/** 短列表(≤2 值且每值 ≤160 字)视为摘要直接可见; 长列表默认折叠。 */
export function isSummary(entry: EvidenceEntry): boolean {
  return entry.values.length <= 2 && entry.values.every((v) => v.length <= 160);
}
