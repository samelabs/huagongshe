"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Avatar } from "@/components/ui/Avatar";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { FollowButton } from "@/components/shared/FollowButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { Tag } from "@/components/ui/Tag";
import { ApiError, reactionSvgUrl } from "@/lib/api";
import type { LoadState, Notice, Reaction } from "./types";
import type { Locale } from "@/lib/i18n/locales";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

/* ── 面板头部（§6 Step 9）：标题 fs-22 650，计数紧随标题；副标题一行
   muted；右侧放主要操作。手机允许换行，操作落到标题下方（修「新建笔记」
   与计数重叠）。 ─────────────────────────────────────── */
export function PanelHeading({ title, subtitle, count, unit = "", action }: {
  title: string;
  subtitle?: string;
  count?: number | string;
  unit?: string;
  action?: ReactNode;
}) {
  return (
    <div className="wb-panel-head">
      <div className="wb-panel-head-main">
        <h2>
          {title}
          {count !== undefined && <span className="wb-panel-count">{count} {unit}</span>}
        </h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action && <div className="wb-panel-head-side">{action}</div>}
    </div>
  );
}

/* ── 统一分页（§6 Step 9）：上一页 / 页码 / 下一页，按钮 ghost sm ── */
export function Pagination({ page, pageSize, total, href }: {
  page: number;
  pageSize: number;
  total: number;
  href: (page: number) => string;
}) {
  const t = useDictionary();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav className="wb-pagination" aria-label={t.common.pageNav}>
      {page > 1
        ? <Link className="hg-btn ghost sm" href={href(page - 1)}>{t.common.prev}</Link>
        : <span className="hg-btn ghost sm" aria-disabled="true">{t.common.prev}</span>}
      <small className="wb-pagination-page">{page} / {pages}</small>
      {page < pages
        ? <Link className="hg-btn ghost sm" href={href(page + 1)}>{t.common.next}</Link>
        : <span className="hg-btn ghost sm" aria-disabled="true">{t.common.next}</span>}
    </nav>
  );
}

/* ── 工作台统一列表行（§6 Step 9）：概览「我的内容」与各面板列表共用。
   结构 = 类型图标/缩略图 ｜ 标题(整行点击目标)+元信息 ｜ 右侧展示+操作。
   整行点击靠标题链接的 ::after 铺满行（CSS）；actions 内按钮层级更高，
   不会误触发行跳转。 ──────────────────────────────────── */
export function WbListRow({ href, icon, iconTone, thumb, title, meta, side, actions, ariaLabel }: {
  /** 整行点击目标（标题链接铺满整行） */
  href: string;
  /** 36px 类型图标块（.wb-row-icon） */
  icon?: ReactNode;
  iconTone?: "note" | "reaction";
  /** 缩略图（结构式/方程式，替代 icon） */
  thumb?: ReactNode;
  title: ReactNode;
  /** Tag / EntityBadge xs / time 等元信息 */
  meta?: ReactNode;
  /** 右侧静态信息（日期、人数…） */
  side?: ReactNode;
  /** 右侧操作按钮（层级高于整行链接） */
  actions?: ReactNode;
  ariaLabel?: string;
}) {
  const locale = useLocale();
  return (
    <article className="wb-row">
      {icon && <span className={`wb-row-icon${iconTone ? ` ${iconTone}` : ""}`} aria-hidden="true">{icon}</span>}
      {thumb && <span className="wb-row-thumb" aria-hidden="true">{thumb}</span>}
      <span className="wb-row-main">
        <Link href={withLocale(href, locale)} className="wb-row-title" aria-label={ariaLabel}>{title}</Link>
        {meta && <span className="wb-row-meta">{meta}</span>}
      </span>
      {(side != null || actions) && (
        <span className="wb-row-side">
          {side}
          {actions && <span className="wb-row-actions">{actions}</span>}
        </span>
      )}
    </article>
  );
}

/* ── 加载骨架（§6 Step 9：统一用 ui/Skeleton）── */
export function PanelLoading({ variant = "grid", rows = 4 }: { variant?: "grid" | "list"; rows?: number }) {
  if (variant === "list") {
    return (
      <div className="wb-skeleton-list" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} variant="row" style={{ width: `${88 - i * 6}%` }} />
        ))}
      </div>
    );
  }
  return (
    <div className="wb-skeleton-grid" aria-hidden="true">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} variant="card" />
      ))}
    </div>
  );
}

/** 相对时间（分钟/小时/天；超过 30 天回退绝对日期）— 概览与动态面板共用 */
export function relativeTime(value: string, locale: string): string {
  const date = new Date(value).getTime();
  if (!Number.isFinite(date)) return value;
  const minutes = Math.round((Date.now() - date) / 60000);
  const fmt = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  if (minutes < 1) return fmt.format(0, "minute");
  if (minutes < 60) return fmt.format(-minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (hours < 24) return fmt.format(-hours, "hour");
  const days = Math.round(hours / 24);
  if (days <= 30) return fmt.format(-days, "day");
  return new Date(value).toLocaleDateString(locale);
}

/** 笔记标题行：首个非空行（≤60 字）— 概览与笔记面板共用 */
export function noteHeadline(content: string): string {
  const first = content.split("\n").map((l) => l.trim()).find((l) => l.length > 0) ?? "";
  return first.length > 60 ? `${first.slice(0, 60)}…` : first;
}

/** 可见性 Tag（概览行与笔记/反应面板行共用） */
export function VisibilityTag({ visibility, t }: { visibility: "public" | "private"; t: Dictionary }) {
  return visibility === "private"
    ? <Tag>{t.common.private}</Tag>
    : <Tag tone="blue">{t.common.public}</Tag>;
}

/* ── 动态卡片（§9.4）：概览「关注动态」与动态面板（?tab=activity）同一个
   组件（Step 9 Part B.4）。v1.7 只有 new_reaction 事件。 ── */
export function ActivityFeedCard({ item, favored, t, locale }: {
  item: Notice;
  /** 收藏初始态（调用方从 /users/me/follows/reactions 的 id 集给出） */
  favored: boolean;
  t: Dictionary;
  locale: Locale;
}) {
  return (
    <article className="wb-feed-item">
      <Avatar id={item.actor_username} name={item.actor_display_name || item.actor_username} size={32} />
      <div className="wb-feed-body">
        <p className="wb-feed-line">
          {t.me.feedActor(item.actor_display_name || item.actor_username)}
          <EntityBadge kind="reaction" id={item.reaction_id} size="xs" href={withLocale(`/reaction/${item.reaction_id}`, locale)} ariaLabel={t.common.hridLabel(item.reaction_id)} />
        </p>
        <time dateTime={item.created_at}>{relativeTime(item.created_at, locale)}</time>
        <Link className="wb-feed-eq" href={withLocale(`/reaction/${item.reaction_id}`, locale)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(item.reaction_id, 720, 160)} height={64} alt={t.reaction.equationAlt(item.reaction_id)} loading="lazy" />
        </Link>
        <div className="wb-feed-actions">
          <FollowButton
            endpoint={`/reactions/${item.reaction_id}/follow`}
            initial={favored}
            showCount={false}
            label="favor"
            variant="ghost"
            size="sm"
          />
          <Link className="hg-btn ghost sm" href={withLocale(`/reaction/${item.reaction_id}`, locale)}>{t.me.feedOpen}</Link>
        </div>
      </div>
    </article>
  );
}

/* ── 反应行（§6）：方程式缩略图（高 48）+ HRID 徽标 sm（私有锁）+ 摘要 +
   日期 + 关注人数 —— 「我的反应」与「收藏·反应」共用（Step 9 Part B）── */
export function ReactionRow({ item, t, locale, actions }: {
  item: Reaction;
  t: Dictionary;
  locale: Locale;
  actions?: ReactNode;
}) {
  return (
    <WbListRow
      href={`/reaction/${item.id}`}
      thumb={
        // eslint-disable-next-line @next/next/no-img-element
        <img src={reactionSvgUrl(item.id, 360, 96)} height={48} alt="" loading="lazy" />
      }
      title={
        <EntityBadge
          kind="reaction"
          id={item.id}
          size="sm"
          state={item.visibility === "private" ? "private" : undefined}
          ariaLabel={t.common.hridLabel(item.id)}
        />
      }
      meta={
        <>
          {item.reaction_smiles && <code className="wb-row-code" title={item.reaction_smiles}>{item.reaction_smiles}</code>}
          {item.updated_at && <time dateTime={item.updated_at}>{relativeTime(item.updated_at, locale)}</time>}
        </>
      }
      side={
        <>
          {item.followers != null && <span className="wb-row-side-info">{t.user.peopleCount(item.followers)}</span>}
          {actions && <span className="wb-row-actions">{actions}</span>}
        </>
      }
      ariaLabel={t.common.hridLabel(item.id)}
    />
  );
}

/**
 * 按 ApiError.status 映射到精确错误文案。
 * 复用主站 search.err* 和 common.networkError，与主站同一套文案源。
 */
export function panelErrorMessage(error: unknown, t: { search: { errLoginRequired: string; errRateLimit: string; errTimeout: string; errIncomplete: string; errUnrecognized: string; errNotFound: string; errGeneric: string }; common: { networkError: string } }): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      // 0904 P1收口: 401 此前落 errGeneric"稍后重试"误导 — 会话过期重试永远
      // 失败, 应提示登录(主站 search/page.tsx 已有同款映射)。
      case 401: return t.search.errLoginRequired;
      case 429: return t.search.errRateLimit;
      case 503: return t.search.errTimeout;
      case 422: return t.search.errIncomplete;
      case 400: return t.search.errUnrecognized;
      case 404: return t.search.errNotFound;
      default:  return t.search.errGeneric;
    }
  }
  return t.common.networkError;
}

export function PanelError({ error }: { error?: unknown }) {
  const t = useDictionary();
  const message = error ? panelErrorMessage(error, t) : t.me.errPanel;
  return <p className="wb-state wb-state-error" role="alert">{message}</p>;
}

export type { LoadState };
