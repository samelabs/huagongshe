"use client";

/**
 * ProfileHeader — 公开主页社交名片头部（v1.7 Step 10，DESIGN_SYSTEM §9.5）。
 * 桌面三列：Avatar 80 | 信息 | 操作。信息依次为 展示名(fs-28/650) + 关系 Tag
 * （互相关注 > 关注了你）→ @username → 职位·机构 → 简介(fs-14/text-2/60ch)
 * → 元信息行（机构图标、加入时间）→ 数据行（公开反应 · 公开笔记 · 粉丝 · 关注，
 * 数字 650、标签 muted）。
 * 操作：访客 = 关注（primary 乐观更新，已关注转 secondary hover「取消关注」）
 * + 分享（复制链接 + Toast）；本人 = 编辑资料(secondary) + 进入工作台(primary)。
 * 关注/取消时头部数据行的粉丝数同步 ±1（FollowButton onChange）。
 * 手机（≤640，参考 §12 第三屏）：头像 64 + 反应/粉丝/关注 三数横排 → 名字+
 * 关系 Tag → 简介 → 职位·机构 → 关注 + 分享主页 两个 lg 文字按钮并排等宽
 * （分享桌面仍为 ghost 图标，CSS 切换，Part E）。
 */
import Link from "next/link";
import { useState } from "react";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { FollowButton } from "@/components/shared/FollowButton";
import { ShareButton } from "@/components/ShareButton";
import { Tag } from "@/components/ui/Tag";
import { IconPin, IconCal } from "@/components/ui/icons";

export type ProfileHeaderData = {
  id: number;
  username: string;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
  created_at: string;
  institution: string | null;
  title: string | null;
  followers: number;
  following: number;
  public_reactions: number;
  notes: number;
  is_following: boolean;
  is_followed_by: boolean;
  is_mutual: boolean;
  is_me: boolean;
};

export function ProfileHeader({ profile }: { profile: ProfileHeaderData }) {
  const t = useDictionary();
  const locale = useLocale();
  // 关注操作联动头部「粉丝」计数（乐观 ±1，撤销时回退 —— FollowButton onChange）
  const [followers, setFollowers] = useState(profile.followers);
  const joined = new Date(profile.created_at).toLocaleDateString(locale);
  const jobTitle = [profile.title, profile.institution].filter(Boolean).join(" · ");
  // 本人：粉丝/关注链接到工作台列表页；他人无公开列表页 → 纯展示
  const followersHref = profile.is_me ? withLocale("/aichem?tab=followers", locale) : null;
  const followingHref = profile.is_me ? withLocale("/aichem?tab=following", locale) : null;

  return (
    <header className="pf-head">
      <Avatar id={profile.id} name={profile.display_name} src={profile.avatar_url} size={80} />
      <div className="pf-info">
        <h1>
          {profile.display_name}
          {profile.is_mutual && <Tag tone="blue">{t.follow.mutual}</Tag>}
          {!profile.is_mutual && profile.is_followed_by && <Tag tone="blue">{t.follow.followsYou}</Tag>}
        </h1>
        <p className="pf-handle">@{profile.username}</p>
        {jobTitle && <p className="pf-job">{jobTitle}</p>}
        {profile.bio && <p className="pf-bio">{profile.bio}</p>}
        <div className="pf-meta">
          {profile.institution && (
            <span><IconPin aria-hidden="true" />{profile.institution}</span>
          )}
          <span><IconCal aria-hidden="true" />{t.user.joinedAt(joined)}</span>
        </div>
        <div className="pf-counts">
          <span><strong>{profile.public_reactions}</strong>{t.user.tabReactions}</span>
          <span><strong>{profile.notes}</strong>{t.user.tabNotes}</span>
          {followersHref
            ? <Link href={followersHref}><strong>{followers}</strong>{t.user.followers}</Link>
            : <span><strong>{followers}</strong>{t.user.followers}</span>}
          {followingHref
            ? <Link href={followingHref}><strong>{profile.following}</strong>{t.user.following}</Link>
            : <span><strong>{profile.following}</strong>{t.user.following}</span>}
        </div>
      </div>
      <div className="pf-acts">
        {profile.is_me ? (
          <>
            <Button variant="secondary" href={withLocale("/me/settings/profile", locale)}>{t.user.editProfile}</Button>
            <Button variant="primary" href={withLocale("/aichem", locale)}>{t.user.enterWorkbench}</Button>
          </>
        ) : (
          <>
            <FollowButton
              endpoint={`/users/${encodeURIComponent(profile.username)}/follow`}
              initial={profile.is_following}
              showCount={false}
              activeVariant="secondary"
              activeHoverText={t.follow.unfollow}
              onChange={(next) => setFollowers((value) => Math.max(value + (next ? 1 : -1), 0))}
            />
            {/* Step 10 Part E（§12 第三屏）：桌面 ghost 图标；手机 secondary lg
                文字「分享主页」（与关注并排等宽）—— 两个形态 CSS 切换，行为同源。 */}
            <span className="pf-share">
              <ShareButton iconOnly title={`${profile.display_name}｜${t.brand.name}`} ariaLabel={t.me.profileShareLabel} className="pf-share-icon" />
              <ShareButton title={`${profile.display_name}｜${t.brand.name}`} label={t.user.shareProfile} variant="secondary" size="lg" ariaLabel={t.me.profileShareLabel} feedback="toast" className="pf-share-text" />
            </span>
          </>
        )}
      </div>
    </header>
  );
}
