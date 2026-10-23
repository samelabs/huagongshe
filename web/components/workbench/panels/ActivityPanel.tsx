"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphRx } from "@/components/ui/icons";
import { apiGet, apiPost } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useWorkbenchCounts } from "../WorkbenchCountsContext";
import { ActivityFeedCard, PanelError, PanelHeading, PanelLoading, Pagination, SlowNotice } from "../shared";
import type { LoadState, NoticeResponse, PageResponse, PanelProps, Reaction } from "../types";

const empty = (): NoticeResponse => ({ items: [], total: 0, page: 1, page_size: 50 });

/** 通知面板（?tab=activity）：收件箱的表达位。
 * 已读/未读是逐条状态：未读条目带标记，点开通知指向的内容即单条已读，
 * 「全部已读」批量置位 —— 进入面板本身不改变已读状态（未读数由
 * WorkbenchCounts.refresh → router.refresh → SSR 重取保持与列表同口径）。 */
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

  /** 客户端重载（请求序号防串台）；SSR 命中时直接用预取数据 */
  async function load() {
    const requestId = ++latestLoad.current;
    setState("loading");
    setError(null);
    try {
      const value = await apiGet<NoticeResponse>(`/users/me/notifications?page=${page}&page_size=50`);
      if (requestId !== latestLoad.current) return;
      setNotices(value);
      setState("ready");
    } catch (err) {
      if (requestId !== latestLoad.current) return;
      setError(err);
      setState("error");
    }
  }

  /** 单条已读：点开通知指向的内容即消费该通知（乐观置位；失败不回滚，
   * 下次进入面板由列表口径自愈）。 */
  function markRead(id: number) {
    setNotices((current) => current ? {
      ...current,
      items: current.items.map((n) => n.id === id && !n.read_at ? { ...n, read_at: new Date().toISOString() } : n),
    } : current);
    apiPost(`/users/me/notifications/${id}/read`).then(() => refreshCounts()).catch(() => {});
  }

  /** 全量已读（后端按收件人全量置位，含动态流不可见的残留行） */
  async function markAllRead() {
    const stamp = new Date().toISOString();
    setNotices((current) => current ? {
      ...current,
      items: current.items.map((n) => ({ ...n, read_at: n.read_at ?? stamp })),
    } : current);
    try {
      await apiPost("/users/me/notifications/read");
      refreshCounts();
    } catch {
      void load();
    }
  }

  useEffect(() => {
    if (!mounted.current && initialData) {
      mounted.current = true;
      return;
    }
    mounted.current = true;
    void load();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  return (
    <section className="wb-panel">
      <PanelHeading
        title={t.me.tabNotifications}
        count={state === "ready" ? notices.total : undefined}
        action={state === "ready" && notices.items.some((n) => !n.read_at) ? (
          <Button variant="ghost" size="sm" onClick={() => void markAllRead()}>{t.me.markAllRead}</Button>
        ) : undefined}
      />
      {state === "loading" && <><PanelLoading variant="list" /><SlowNotice active onRetry={() => void load()} /></>}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (notices.items.length
        ? <div className="wb-feed-list">
            {notices.items.map((item) => (
              <ActivityFeedCard
                key={item.id}
                item={item}
                favored={item.reaction_id != null ? favoredIds.has(item.reaction_id) : false}
                t={t}
                locale={locale}
                onOpen={() => markRead(item.id)}
              />
            ))}
          </div>
        : <EmptyState icon={<GlyphRx />} title={t.me.notificationsEmptyTitle} action={{ label: t.me.discoverCta, href: withLocale("/aichem?tab=people", locale) }}>{t.me.notificationsEmptyDesc}</EmptyState>)}
      {state === "ready" && notices.total > notices.page_size && (
        <Pagination page={page} pageSize={notices.page_size} total={notices.total} href={(value) => withLocale(`/aichem?tab=activity${value > 1 ? `&page=${value}` : ""}`, locale)} />
      )}
    </section>
  );
}
