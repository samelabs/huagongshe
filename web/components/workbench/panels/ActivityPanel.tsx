"use client";

import { useEffect, useRef, useState } from "react";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphRx } from "@/components/ui/icons";
import { apiGet, apiPost } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useWorkbenchCounts } from "../WorkbenchCountsContext";
import { ActivityFeedCard, PanelError, PanelHeading, PanelLoading, Pagination, SlowNotice } from "../shared";
import type { LoadState, NoticeResponse, PageResponse, PanelProps, Reaction } from "../types";

const empty = (): NoticeResponse => ({ items: [], total: 0, page: 1, page_size: 50 });

/** 通知面板（?tab=activity）：通知是唯一表达位（归位裁定，2026-10）。
 * 进入面板后按现有逻辑标记已读，侧栏与底部 tab 的
 * 未读数同步清零（WorkbenchCounts.refresh → router.refresh → SSR 重取）。 */
export function ActivityPanel({ page, initialData }: PanelProps & { initialData?: NoticeResponse | null }) {
  const t = useDictionary();
  const locale = useLocale();
  const [notices, setNotices] = useState<NoticeResponse>(initialData ?? empty());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  /** 通知卡收藏初始态：/users/me/follows/reactions 的 id 集 */
  const [favoredIds, setFavoredIds] = useState<Set<number>>(new Set());
  const { refresh: refreshCounts } = useWorkbenchCounts();
  const mounted = useRef(false);
  const latestLoad = useRef(0);

  useEffect(() => {
    let active = true;
    apiGet<PageResponse<Reaction>>("/users/me/follows/reactions?page=1&page_size=50")
      .then((value) => { if (active) setFavoredIds(new Set(value.items.map((item) => item.id))); })
      .catch(() => {});
    return () => { active = false; };
  }, [page]);

  /** 客户端重载（请求序号防串台）；SSR 命中时只补标记已读 */
  async function load() {
    const requestId = ++latestLoad.current;
    setState("loading");
    setError(null);
    try {
      const value = await apiGet<NoticeResponse>(`/users/me/notifications?page=${page}&page_size=50`);
      if (requestId !== latestLoad.current) return;
      setNotices(value);
      setState("ready");
      if (page === 1 && value.items.some((item) => !item.read_at)) {
        await apiPost("/users/me/notifications/read").catch(() => {});
        if (requestId !== latestLoad.current) return;
        setNotices((current) => ({ ...current, items: current.items.map((item) => ({ ...item, read_at: item.read_at || new Date().toISOString() })) }));
        refreshCounts();
      }
    } catch (err) {
      if (requestId !== latestLoad.current) return;
      setError(err);
      setState("error");
    }
  }

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
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  return (
    <section className="wb-panel">
      <PanelHeading title={t.me.tabNotifications} count={state === "ready" ? notices.total : undefined} />
      {state === "loading" && <><PanelLoading variant="list" /><SlowNotice active onRetry={() => void load()} /></>}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (notices.items.length
        ? <div className="wb-feed-list">
            {notices.items.map((item) => (
              <ActivityFeedCard key={item.id} item={item} favored={item.reaction_id != null ? favoredIds.has(item.reaction_id) : false} t={t} locale={locale} />
            ))}
          </div>
        : <EmptyState icon={<GlyphRx />} title={t.me.notificationsEmptyTitle} action={{ label: t.me.discoverCta, href: withLocale("/aichem?tab=people", locale) }}>{t.me.notificationsEmptyDesc}</EmptyState>)}
      {state === "ready" && notices.total > notices.page_size && (
        <Pagination page={page} pageSize={notices.page_size} total={notices.total} href={(value) => withLocale(`/aichem?tab=activity${value > 1 ? `&page=${value}` : ""}`, locale)} />
      )}
    </section>
  );
}
