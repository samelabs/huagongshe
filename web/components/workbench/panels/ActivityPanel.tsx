"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet, apiPost } from "@/lib/api";
import t from "@/lib/i18n";
import { SITE_LOCALE } from "@/lib/locale";
import { useWorkbenchCounts } from "../WorkbenchCountsContext";
import { WbEmpty, Pagination, PanelError, PanelHeading, PanelLoading } from "../shared";
import type { LoadState, NoticeResponse, PanelProps } from "../types";

const empty = (): NoticeResponse => ({ items: [], total: 0, page: 1, page_size: 50 });

export function ActivityPanel({ page, initialData }: PanelProps & { initialData?: NoticeResponse | null }) {
  const [notices, setNotices] = useState<NoticeResponse>(initialData ?? empty());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const { refresh: refreshCounts } = useWorkbenchCounts();
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current && initialData) {
      mounted.current = true;
      // SSR 预取了数据，但仍需标记已读
      if (page === 1 && initialData.items.some((item) => !item.read_at)) {
        apiPost("/users/me/notifications/read").then(() => {
          setNotices((current) => ({ ...current, items: current.items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() })) }));
          refreshCounts();
        }).catch(() => {});
      }
      return;
    }
    mounted.current = true;
    let active = true;
    setState("loading");
    setError(null);
    apiGet<NoticeResponse>(`/users/me/notifications?page=${page}&page_size=50`)
      .then((value) => {
        if (!active) return;
        setNotices(value);
        setState("ready");
        if (page === 1 && value.items.some((item) => !item.read_at)) {
          apiPost("/users/me/notifications/read").then(() => {
            if (!active) return;
            setNotices((current) => ({ ...current, items: current.items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() })) }));
            refreshCounts();
          }).catch(() => {});
        }
      })
      .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    return () => { active = false; };
  }, [page]);

  return (
    <section className="wb-panel">
      <PanelHeading title={t.me.tabActivity} subtitle={t.me.activityHint} />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (notices.items.length
        ? <div className="wb-notice-list">
            {notices.items.map((item) => (
              <article key={item.id}>
                <Link className="wb-notice-actor" href={`/user/${encodeURIComponent(item.actor_username)}`}>
                  <strong>{t.me.activityActor(item.actor_display_name || t.me.activityActorFallback)}</strong>
                  <small>{new Date(item.created_at).toLocaleString(SITE_LOCALE)}</small>
                </Link>
                <Link className="wb-notice-target" href={`/reaction/${item.reaction_id}`}>
                  <EntityId kind="reaction" id={item.reaction_id} compact />
                </Link>
              </article>
            ))}
          </div>
        : <WbEmpty text={t.me.emptyActivity} />)}
      {state === "ready" && notices.total > notices.page_size && (
        <Pagination page={page} pageSize={notices.page_size} total={notices.total} href={(value) => `/aichem?tab=activity${value > 1 ? `&page=${value}` : ""}`} />
      )}
    </section>
  );
}
