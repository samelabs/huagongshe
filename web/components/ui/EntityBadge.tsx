"use client";

/**
 * EntityBadge — HCID / HRID 徽标（DESIGN_SYSTEM §5，参考 §5）。
 *
 * 全站唯一的实体标识展示组件（禁止在别处拼写 HCID/HRID 的显示）：
 *   [字形][前缀] | [编号] —— 前缀段实体色浅底、编号段白底、1px 实体色描边、圆角 6。
 * 编号等宽 tabular-nums，不加千分位、不补零、不截断；HCID/HRID 是专有名词不翻译。
 *
 * 状态：private（HRID 编号后加锁）；merged（虚线+删除线，redirectTo 时接 → 新徽标）；
 * deleted（虚线+删除线，后跟「已删除」）。merged/deleted 的旧编号不再可点。
 *
 * href 传了渲染 next/link（整徽标即链接）；没传渲染 span（避免与外层链接嵌套）。
 * 本文件与 i18n 字典是 HCID/HRID 前缀字面量的唯一合法所在地（契约测试第 8 条）。
 */
import Link from "next/link";
import { useDictionary } from "@/components/shared/I18nContext";
import { CopyButton } from "./CopyButton";
import { GlyphChem, GlyphRx, IconLock } from "./icons";

export type EntityBadgeKind = "chemical" | "reaction";
export type EntityBadgeSize = "xs" | "sm" | "md" | "lg";
export type EntityBadgeState = "private" | "merged" | "deleted";

export function EntityBadge({ kind, id, size = "sm", href, copyable, compact, state, redirectTo, ariaLabel, className }: {
  kind: EntityBadgeKind;
  id: number | string;
  /** 20(xs 列表/行内) / 24(sm 默认) / 28(md 卡片标题) / 32(lg 详情页头) */
  size?: EntityBadgeSize;
  /** 传入后整个徽标渲染为链接 */
  href?: string;
  /** 右侧附带复制按钮（mini） */
  copyable?: boolean;
  /** 只显示字形 + 编号（表格列；前缀文字保留在 DOM 供无障碍，CSS 隐藏） */
  compact?: boolean;
  /** private：编号后锁标；merged/deleted：见组件头注释 */
  state?: EntityBadgeState;
  /** merged 时显示 → 新编号徽标 */
  redirectTo?: number | string;
  /** 覆盖默认 aria-label（默认「HCID 2244，化合物」类文案取自字典） */
  ariaLabel?: string;
  /** 追加类名（兼容层 entity-id 定位规则经此传入） */
  className?: string;
}) {
  const t = useDictionary();
  const prefix = kind === "chemical" ? "HCID" : "HRID";
  const label = ariaLabel
    ?? (kind === "chemical" ? t.common.hcidLabel(id) : t.common.hridLabel(id));

  const sizeClass = size === "sm" ? "" : size;
  const rootClass = [
    "hg-eb",
    kind === "chemical" ? "chem" : "rx",
    sizeClass,
    compact ? "compact" : "",
    state === "merged" || state === "deleted" ? "gone" : "",
    className ?? "",
  ].filter(Boolean).join(" ");

  const inner = (
    <>
      <span className="k">
        {kind === "chemical" ? <GlyphChem /> : <GlyphRx />}
        <span>{prefix}</span>
      </span>
      <span className="v">{id}</span>
      {state === "private" && (
        <span className="x" title={t.common.private}>
          <IconLock />
        </span>
      )}
    </>
  );

  // merged / deleted：旧编号展示为不可点的 gone 徽标（redirectTo → 新徽标 / 已删除）
  if (state === "merged" || state === "deleted") {
    return (
      <span className="hg-eb-wrap">
        <span className={rootClass} aria-label={label}>{inner}</span>
        {state === "merged" && redirectTo != null ? (
          <>
            <span className="hg-eb-note" aria-hidden="true">→</span>
            <EntityBadge kind={kind} id={redirectTo} size={size} href={href} ariaLabel={ariaLabel} />
          </>
        ) : null}
        {state === "deleted" && <span className="hg-eb-note">{t.common.deletedEntity}</span>}
      </span>
    );
  }

  const badge = href ? (
    <Link href={href} className={rootClass} aria-label={label}>{inner}</Link>
  ) : (
    <span className={rootClass} aria-label={label}>{inner}</span>
  );

  if (copyable) {
    return (
      <span className="hg-eb-copy">
        {badge}
        <CopyButton mini value={String(id)} ariaLabel={`${t.common.copy} ${prefix} ${id}`} />
      </span>
    );
  }
  return badge;
}
