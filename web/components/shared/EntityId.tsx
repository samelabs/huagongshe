"use client";

/**
 * EntityId — EntityBadge 的兼容包装（v1.7 Step 4 起视觉由 EntityBadge 承载）。
 *
 * 旧调用方不改：compact=true → size="xs"，否则 size="sm"；
 * ariaLabel 透传。根元素保留 legacy 类名 entity-id —— globals.css /
 * aichem.css 里的既有定位规则（margin / flex 收缩 / 兄弟选择器）继续生效，
 * 排版规则已由 EntityBadge 的 .hg-eb 样式接管（旧排版块已删除）。
 * HCID/HRID 字面量只存在于 EntityBadge 与 i18n 字典（契约测试第 8 条）。
 */
import { EntityBadge, type EntityBadgeKind } from "@/components/ui/EntityBadge";

export function EntityId({ kind, id, compact = false, ariaLabel }: {
  kind: EntityBadgeKind;
  id: number | string;
  compact?: boolean;
  /** 覆盖默认 aria-label；未传用当前字典 hcidLabel/hridLabel */
  ariaLabel?: string;
}) {
  return (
    <EntityBadge
      kind={kind}
      id={id}
      size={compact ? "xs" : "sm"}
      ariaLabel={ariaLabel}
      className="entity-id"
    />
  );
}
