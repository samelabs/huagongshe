"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphRx } from "@/components/ui/icons";
import { Segmented } from "@/components/ui/Segmented";
import { apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { PanelError, PanelHeading, PanelLoading, Pagination, ReactionRow } from "../shared";
import type { LoadState, PanelProps, ReactionResponse, ReactionVisibility } from "../types";

const empty = (): ReactionResponse => ({ items: [], counts: { all: 0, public: 0, private: 0 }, page: 1, page_size: 20 });

export function ReactionsPanel({ visibility, page, initialData }: PanelProps & { visibility: ReactionVisibility; initialData?: ReactionResponse | null }) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
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

  const subtitle: Record<ReactionVisibility, string> = { all: t.me.visAll, private: t.me.visPrivate, public: t.me.visPublic };
  const total = data.counts[visibility];

  /** §6 Step 9：筛选用 Segmented，仍走 URL 参数（SSR 预取一致） */
  function switchVisibility(value: ReactionVisibility) {
    if (value === visibility) return;
    router.push(withLocale(`/aichem?tab=mine&visibility=${value}`, locale));
  }

  return (
    <section className="wb-panel">
      <PanelHeading
        title={t.me.tabReactions}
        subtitle={subtitle[visibility]}
        count={state === "ready" ? total : "—"}
        unit={t.me.unitReaction}
        action={<Button variant="primary" size="sm" href={withLocale("/submit", locale)}>{t.me.navNewReaction}</Button>}
      />
      <Segmented
        ariaLabel={t.me.filterReactions}
        options={[
          { value: "all" as const, label: t.me.filterAll },
          { value: "private" as const, label: t.common.private },
          { value: "public" as const, label: t.common.public },
        ]}
        value={visibility}
        onChange={(value) => switchVisibility(value)}
      />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (data.items.length
        ? <div className="wb-row-list">{data.items.map((item) => <ReactionRow key={item.id} item={item} t={t} locale={locale} />)}</div>
        : <EmptyState icon={<GlyphRx />} title={t.me.emptyReactions} action={{ label: t.me.navNewReaction, href: withLocale("/submit", locale) }} />)}
      {state === "ready" && total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={total} href={(value) => {
          return withLocale(
            `/aichem?tab=mine${visibility === "all" ? "" : `&visibility=${visibility}`}${value > 1 ? `&page=${value}` : ""}`,
            locale,
          );
        }} />
      )}
    </section>
  );
}
