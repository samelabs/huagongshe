"use client";

import Link from "next/link";
import t from "@/lib/i18n";
import { DashboardEmpty, Pagination, PanelError, PanelHeading, PanelLoading, ReactionCards } from "../shared";
import type { LoadState, ReactionResponse, ReactionVisibility } from "../types";

export function ReactionsPanel({ data, state, visibility, page }: {
  data: ReactionResponse;
  state: LoadState;
  visibility: ReactionVisibility;
  page: number;
}) {
  const labels: Record<ReactionVisibility, string> = { all: t.me.filterAll, private: t.common.private, public: t.common.public };
  const subtitle: Record<ReactionVisibility, string> = { all: t.me.visAll, private: t.me.visPrivate, public: t.me.visPublic };
  const total = data.counts[visibility];
  return (
    <section>
      <PanelHeading title={t.me.tabReactions} subtitle={subtitle[visibility]} count={state === "ready" ? total : "—"} unit={t.me.unitReaction} />
      <nav className="wb-filters" aria-label={t.me.filterReactions}>
        {(["all", "private", "public"] as ReactionVisibility[]).map((value) => (
          <Link href={value === "all" ? "/aichem" : `/aichem?visibility=${value}`} className={visibility === value ? "active" : ""} key={value}>{labels[value]}</Link>
        ))}
      </nav>
      {state === "loading" && <PanelLoading />}
      {state === "error" && <PanelError />}
      {state === "ready" && (data.items.length
        ? <ReactionCards items={data.items} editable />
        : <DashboardEmpty text={visibility === "all" ? t.me.emptyReactions : `${t.me.emptyReactions}`} action />)}
      {state === "ready" && total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={total} href={(value) => {
          const filter = visibility === "all" ? "" : `visibility=${visibility}`;
          return `/aichem?${[filter, value > 1 ? `page=${value}` : ""].filter(Boolean).join("&")}`.replace(/\?$/, "");
        }} />
      )}
    </section>
  );
}
