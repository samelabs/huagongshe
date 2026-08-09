"use client";

import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import { reactionSvgUrl } from "@/lib/api";
import t from "@/lib/i18n";
import type { LoadState, Reaction } from "./types";

export function PanelHeading({ title, subtitle, count, unit = "" }: {
  title: string;
  subtitle?: string;
  count?: number | string;
  unit?: string;
}) {
  return (
    <div className="wb-panel-head">
      <div>
        <h2>{title}</h2>
        {subtitle && <span>{subtitle}</span>}
      </div>
      {count !== undefined && <strong>{count} {unit}</strong>}
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

export function DashboardEmpty({ text, action = false }: { text: string; action?: boolean }) {
  return (
    <div className="wb-empty">
      <p>{text}</p>
      {action && <Link className="wb-btn wb-btn-ghost" href="/submit">{t.nav.newReaction}</Link>}
    </div>
  );
}

export function PanelLoading() {
  return <p className="wb-state">{t.common.loading}</p>;
}

export function PanelError() {
  return <p className="wb-state wb-state-error">{t.me.errPanel}</p>;
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
          <Link className="wb-card-img" href={`/reaction/${item.id}`}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} />
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
