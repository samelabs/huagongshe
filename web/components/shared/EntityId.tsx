import t from "@/lib/i18n";

/**
 * EntityId — HCID/HRID 平台实体身份的唯一实现（Design System v2）。
 *
 * HCID = chemistry.chemicals.id，HRID = chemistry.reactions.id。
 * 它们是 Huagongshe 平台记录引用，不是 CAS/CID/InChIKey 这类科学标识：
 * 无 zero padding、无 synthetic encoding、不改数据库 ID，显示即 `HCID 178750460`。
 *
 * - full（默认）：实体详情 header —— 强于普通 metadata、弱于实体名称
 * - compact：搜索结果 / 反应成分卡 / 列表卡 —— 同语义同几何，仅收小 padding/字号
 * - chemical 与 reaction 只差 accent（蓝 / 灰蓝），几何完全同构
 *
 * ariaLabel 默认保持静态 zh；已迁移 runtime locale 的调用方（Search 结果卡）
 * 传入当前请求语言文案。Search 链全部迁移后, 默认值再统一切换来源。
 */
export function EntityId({ kind, id, compact = false, ariaLabel }: {
  kind: "chemical" | "reaction";
  id: number | string;
  compact?: boolean;
  /** 覆盖默认 aria-label（中文 hcidLabel/hridLabel）；未传保持中文默认 */
  ariaLabel?: string;
}) {
  const prefix = kind === "chemical" ? "HCID" : "HRID";
  const label = ariaLabel
    ?? (kind === "chemical"
      ? t.common.hcidLabel(id)
      : t.common.hridLabel(id));
  return (
    <span className={`entity-id ${kind}${compact ? " compact" : ""}`} aria-label={label}>
      <span>{prefix}</span><strong>{id}</strong>
    </span>
  );
}
