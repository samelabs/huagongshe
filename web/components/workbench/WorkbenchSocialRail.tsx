"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAccount } from "@/components/shared/AccountContext";
import { useWorkbenchCounts } from "./WorkbenchCountsContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { IconShare, GlyphRx } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";
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
  const { counts } = useWorkbenchCounts();
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();

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

  function shareProfile() {
    const link = `https://huagongshe.com/u/${encodeURIComponent(user!.username)}`;
    void navigator.clipboard?.writeText(link);
    toast.success(t.me.profileLinkCopied);
  }

  return (
    <div className="wb-home2-col-side">
      {/* ── 我的主页卡片 ── */}
      <section className="wb-card wb-profile-card" data-area="profile">
        <div className="wb-profile-top">
          <Avatar id={user.id} name={user.display_name} src={user.avatar_url} size={40} />
          <div className="wb-profile-id">
            <strong>{user.display_name}</strong>
            <small>@{user.username}</small>
          </div>
          <Button variant="ghost" iconOnly aria-label={t.me.profileShareLabel} onClick={shareProfile}>
            <IconShare />
          </Button>
        </div>
        <div className="wb-profile-stats">
          <Link href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)}>
            <strong>{counts?.public_reactions ?? 0}</strong><span>{t.user.publicReactions}</span>
          </Link>
          <Link href={withLocale("/aichem?tab=followers", locale)}>
            <strong>{counts?.followers ?? 0}</strong><span>{t.user.followers}</span>
          </Link>
          <Link href={withLocale("/aichem?tab=following", locale)}>
            <strong>{counts?.following ?? 0}</strong><span>{t.user.following}</span>
          </Link>
        </div>
        <Button variant="secondary" size="sm" className="wb-profile-cta" href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)}>
          {t.me.profileViewPublic}
        </Button>
      </section>

      {/* ── 关注动态 ── */}
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
