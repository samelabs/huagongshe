"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import t from "@/lib/i18n";
import { WbEmpty, Pagination, PanelError, PanelHeading, PanelLoading, ReactionCards } from "../shared";
import type { LoadState, PanelProps, ReactionResponse, ReactionVisibility } from "../types";

const empty = (): ReactionResponse => ({ items: [], counts: { all: 0, public: 0, private: 0 }, page: 1, page_size: 20 });

export function ReactionsPanel({ visibility, page, initialData }: PanelProps & { visibility: ReactionVisibility; initialData?: ReactionResponse | null }) {
  const [data, setData] = useState<ReactionResponse>(initialData ?? empty());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(false);

  useEffect(() => {
    // 首次渲染有 SSR 预取数据时跳过；后续翻页/切筛选走客户端 fetch
    if (!mounted.current && initialData) { mounted.current = true; return; }
    mounted.current = true;
    let active = true;
    setState("loading");
    setError(null);
    apiGet<ReactionResponse>(`/users/me/reactions?visibility=${visibility}&page=${page}&page_size=20`)
      .then((value) => { if (active) { setData(value); setState("ready"); } })
      .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    return () => { active = false; };
  }, [visibility, page]);

  const labels: Record<ReactionVisibility, string> = { all: t.me.filterAll, private: t.common.private, public: t.common.public };
  const subtitle: Record<ReactionVisibility, string> = { all: t.me.visAll, private: t.me.visPrivate, public: t.me.visPublic };
  const total = data.counts[visibility];

  return (
    <section className="wb-panel">
      <PanelHeading
        title={t.me.tabReactions}
        subtitle={subtitle[visibility]}
        count={state === "ready" ? total : "—"}
        unit={t.me.unitReaction}
        action={<Link className="wb-btn wb-btn-primary" href="/submit">{t.me.navNewReaction}</Link>}
      />
      <nav className="wb-filters" aria-label={t.me.filterReactions}>
        {(["all", "private", "public"] as ReactionVisibility[]).map((value) => (
          <Link href={`/aichem?tab=mine&visibility=${value}`} className={visibility === value ? "active" : ""} key={value}>{labels[value]}</Link>
        ))}
      </nav>
      {state === "loading" && <PanelLoading />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (data.items.length
        ? <ReactionCards items={data.items} editable />
        : <WbEmpty text={t.me.emptyReactions} action />)}
      {state === "ready" && total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={total} href={(value) => {
          const filter = visibility === "all" ? "" : `visibility=${visibility}`;
          return `/aichem?${[filter, value > 1 ? `page=${value}` : ""].filter(Boolean).join("&")}`.replace(/\?$/, "");
        }} />
      )}
    </section>
  );
}
