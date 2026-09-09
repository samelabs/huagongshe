"use client";

import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { ApiError, reactionSvgUrl } from "@/lib/api";
import t from "@/lib/i18n";
import type { LoadState, Reaction } from "./types";

export function PanelHeading({ title, subtitle, count, unit = "", action }: {
  title: string;
  subtitle?: string;
  count?: number | string;
  unit?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="wb-panel-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <span>{subtitle}</span>}
      </div>
      {action ? <span className="wb-panel-head-side">{action}<strong>{count} {unit}</strong></span> : (count !== undefined ? <strong>{count} {unit}</strong> : null)}
    </div>
  );
}

export function Pagination({ page, pageSize, total, href }: {
  page: number;
  pageSize: number;
  total: number;
  href: (page: number) => string;
}) {
  const pages = Math.ceil(total / pageSize);
  return (
    <nav className="wb-pagination" aria-label={t.common.pageNav}>
      {page > 1 ? <Link href={href(page - 1)}>{t.common.prev}</Link> : <span />}
      <small>{page} / {pages}</small>
      {page < pages ? <Link href={href(page + 1)}>{t.common.next}</Link> : <span />}
    </nav>
  );
}

export function WbEmpty({ text, action = false }: { text: string; action?: boolean }) {
  return (
    <div className="wb-empty">
      <p>{text}</p>
      {action && <Link className="wb-btn wb-btn-ghost" href="/submit">{t.me.navNewReaction}</Link>}
    </div>
  );
}

/** 骨架占位 — variant 匹配最终内容形态，消除加载抖动和宽度跳变 */
export function PanelLoading({ variant = "grid", rows = 4 }: { variant?: "grid" | "list"; rows?: number }) {
  if (variant === "list") {
    return (
      <div className="wb-skeleton-list">
        {Array.from({ length: rows }, (_, i) => (
          <div className="wb-skeleton-row" key={i}>
            <div className="wb-skeleton-avatar" />
            <div className="wb-skeleton-line" />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="wb-skeleton-grid">
      {Array.from({ length: rows }, (_, i) => (
        <div className="wb-skeleton-card" key={i}>
          <div className="wb-skeleton-card-bar" />
          <div className="wb-skeleton-card-img" />
          <div className="wb-skeleton-card-foot" />
        </div>
      ))}
    </div>
  );
}

/**
 * 按 ApiError.status 映射到精确错误文案。
 * 复用主站 search.err* 和 common.networkError，与主站同一套文案源。
 */
export function panelErrorMessage(error: unknown): string {
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
  const message = error ? panelErrorMessage(error) : t.me.errPanel;
  return <p className="wb-state wb-state-error">{message}</p>;
}

export function ReactionCards({ items, editable = false }: { items: Reaction[]; editable?: boolean }) {
  return (
    <div className="wb-grid">
      {items.map((item) => (
        <article key={item.id}>
          <header>
            <Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link>
            {item.updated_at && <span>{new Date(item.updated_at).toLocaleDateString("zh-CN")}</span>}
          </header>
              <Link href={`/reaction/${item.id}`} className="wb-card-img">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={t.reaction.equationAlt(item.id)} />
              </Link>
          <footer>
            <span>{item.visibility === "private" ? t.me.privateVisible : editable ? t.me.publicRecord(item.followers || 0) : t.common.public}</span>
            {editable ? <Link href={`/submit?reaction=${item.id}`}>{t.common.edit}</Link> : <Link href={`/reaction/${item.id}`}>{t.common.view}</Link>}
          </footer>
        </article>
      ))}
    </div>
  );
}

export type { LoadState };
