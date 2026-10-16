"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { EmptyState } from "@/components/ui/EmptyState";
import { GlyphRx } from "@/components/ui/icons";
import { apiGet } from "@/lib/api";
import { ActivityFeedCard } from "./shared";
import type { Notice, NoticeResponse, PageResponse, Reaction } from "./types";

/**
 * 工作台右侧社交栏（DESIGN_SYSTEM 2.1 / 6.7 / I-047 / I-085）：
 * 桌面宽度下所有工作台页面均保留本栏，确保栅格主列宽度与位置稳定。
 * 平板及以下下沉或隐藏，各 Tab 表现一致。
 */
export function WorkbenchSocialRail({
  initialNotices,
  initialFavoredIds,
}: {
  initialNotices?: NoticeResponse | null;
  initialFavoredIds?: number[] | null;
}) {
  const { user } = useAccount();
  const t = useDictionary();
  const locale = useLocale();

  const [feedItems, setFeedItems] = useState<Notice[]>(() => initialNotices?.items.slice(0, 5) ?? []);
  const [favoredIds, setFavoredIds] = useState<Set<number>>(() => new Set(initialFavoredIds ?? []));

  useEffect(() => {
    if (initialNotices) {
      setFeedItems(initialNotices.items.slice(0, 5));
    } else {
      let active = true;
      apiGet<NoticeResponse>("/users/me/notifications?page=1&page_size=5")
        .then((res) => { if (active) setFeedItems(res.items.slice(0, 5)); })
        .catch(() => {});
      return () => { active = false; };
    }
  }, [initialNotices]);

  useEffect(() => {
    if (initialFavoredIds) {
      setFavoredIds(new Set(initialFavoredIds));
    } else {
      let active = true;
      apiGet<PageResponse<Reaction>>("/users/me/follows/reactions?page=1&page_size=50")
        .then((res) => { if (active) setFavoredIds(new Set(res.items.map((i) => i.id))); })
        .catch(() => {});
      return () => { active = false; };
    }
  }, [initialFavoredIds]);

  if (!user) return null;

  return (
    <div className="wb-home2-col-side">
      {/* ── 关注动态（6.7 社交列；「我的主页卡片」已移除 —— 身份与分享
          由顶栏头像菜单、手机抽屉与个人主页承载，卡片在每个 Tab 重复出现属冗余） ── */}
      <section className="wb-card wb-feed-card" data-area="feed">
        <div className="wb-card-head">
          <h3>{t.me.tabActivity}</h3>
        </div>
        {feedItems.length > 0 ? (
          <>
            <div className="wb-feed-list">
              {feedItems.map((item) => (
                <ActivityFeedCard key={item.id} item={item} favored={item.reaction_id != null ? favoredIds.has(item.reaction_id) : false} t={t} locale={locale} />
              ))}
            </div>
            <Link className="wb-feed-all" href={withLocale("/aichem?tab=activity", locale)}>{t.me.feedViewAll}</Link>
          </>
        ) : (
          <EmptyState icon={<GlyphRx />} title={t.me.feedEmptyTitle}>
            {t.me.feedEmptyDesc}
          </EmptyState>
        )}
      </section>
    </div>
  );
}
