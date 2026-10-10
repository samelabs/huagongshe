"use client";

import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphRx } from "@/components/ui/icons";
import { apiGet, apiPost } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useWorkbenchCounts } from "../WorkbenchCountsContext";
import { ActivityFeedCard, PanelError, PanelHeading, PanelLoading, Pagination } from "../shared";
import type { LoadState, NoticeResponse, PageResponse, PanelProps, Reaction } from "../types";

const empty = (): NoticeResponse => ({ items: [], total: 0, page: 1, page_size: 50 });

/** 动态面板（?tab=activity）：与概览「关注动态」同一个卡片组件（§9.4 /
 * Step 9 Part B.4）。进入面板后按现有逻辑标记已读，侧栏与底部 tab 的
 * 未读数同步清零（WorkbenchCounts.refresh → router.refresh → SSR 重取）。 */
export function ActivityPanel({ page, initialData }: PanelProps & { initialData?: NoticeResponse | null }) {
  const t = useDictionary();
  const locale = useLocale();
  const [notices, setNotices] = useState<NoticeResponse>(initialData ?? empty());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  /** 动态卡收藏初始态：/users/me/follows/reactions 的 id 集（与概览同源） */
  const [favoredIds, setFavoredIds] = useState<Set<number>>(new Set());
  const { refresh: refreshCounts } = useWorkbenchCounts();
  const mounted = useRef(false);

  useEffect(() => {
    let active = true;
    apiGet<PageResponse<Reaction>>("/users/me/follows/reactions?page=1&page_size=50")
      .then((value) => { if (active) setFavoredIds(new Set(value.items.map((item) => item.id))); })
      .catch(() => {});
    return () => { active = false; };
  }, [page]);

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
      <PanelHeading title={t.me.tabActivity} subtitle={t.me.activityHint} count={state === "ready" ? notices.total : "—"} />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (notices.items.length
        ? <div className="wb-feed-list">
            {notices.items.map((item) => (
              <ActivityFeedCard key={item.id} item={item} favored={favoredIds.has(item.reaction_id)} t={t} locale={locale} />
            ))}
          </div>
        : <EmptyState icon={<GlyphRx />} title={t.me.emptyActivity} action={{ label: t.me.tabFollowing, href: withLocale("/aichem?tab=following", locale) }} />)}
      {state === "ready" && notices.total > notices.page_size && (
        <Pagination page={page} pageSize={notices.page_size} total={notices.total} href={(value) => withLocale(`/aichem?tab=activity${value > 1 ? `&page=${value}` : ""}`, locale)} />
      )}
    </section>
  );
}
