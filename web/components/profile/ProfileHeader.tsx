"use client";

/**
 * ProfileHeader — 公开主页社交名片头部（DESIGN_SYSTEM 6.6）。
 * 桌面三列：Avatar 80 | 信息 | 操作。信息按社交主页排布：展示名(fs-28/650)
 * + 关系 Tag（互相关注 > 关注了你）→ @username → 简介(fs-14/text-2/60ch)
 * → 元信息行（职位·机构 · 位置 · 个人网址 · ORCID · 加入时间，一行可折行；
 * 职位·机构在这里，不再单占一行与机构重复）→ 数据行（公开反应 · 公开笔记 ·
 * 粉丝 · 关注，数字 650、标签 muted）。
 * 本人名片另有主页短链行：huagongshe.com/u/{username}（规范短址 I-084，
 * 不带 locale，307 协商语言）+ 复制 / 分享两枚图标钮 —— 注意这是主页自身
 * 地址，与元信息行里的「个人网址」（用户自填外部链接）是两回事。
 * 操作（5.5：一组只一个 primary，其余 secondary 同尺寸）：访客 = 关注（primary
 * 乐观更新，已关注转 secondary hover「取消关注」）+ 分享主页；本人 = 编辑资料
 * (secondary) + 进入工作台(primary)，分享由短链行图标承载。分享复制统一
 * Toast 反馈。退出登录不在名片 —— 桌面头像菜单 / 手机抽屉承载（2.3）。
 * 关注/取消时头部数据行的粉丝数同步 ±1（FollowButton onChange）。
 * 手机（≤640，参考 DESIGN_SYSTEM 6.6）：头像 64 + 反应/粉丝/关注 三数横排 →
 * 名字+关系 Tag → @username → 简介 → 元信息行 → 短链行（本人）→ 操作两列
 * 等宽 lg 网格（globals.css .pf-acts）。
 */
import Link from "next/link";
import { useState } from "react";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { CopyButton } from "@/components/ui/CopyButton";
import { FollowButton } from "@/components/shared/FollowButton";
import { ShareButton } from "@/components/ShareButton";
import { Tag } from "@/components/ui/Tag";
import { IconPin, IconCal, IconHome, IconUsers } from "@/components/ui/icons";
import { SITE_ORIGIN } from "@/lib/alternates";

export type ProfileHeaderData = {
  id: number;
  username: string;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
  created_at: string;
  institution: string | null;
  title: string | null;
  location: string | null;
  website: string | null;
  orcid: string | null;
  followers: number;
  following: number;
  public_reactions: number;
  notes: number;
  is_following: boolean;
  is_followed_by: boolean;
  is_mutual: boolean;
  is_me: boolean;
};

/** 网址展示名：过长时只显示主机名 + 路径首段，完整地址留在链接上。 */
function websiteLabel(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname.replace(/\/$/, "");
    const shown = path && path !== "/" ? `${parsed.hostname}${path.slice(0, 24)}${path.length > 24 ? "…" : ""}` : parsed.hostname;
    return shown || url;
  } catch {
    return url;
  }
}

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
  // 分享目标：规范短链（不带 locale，307 到协商语言的主页）；og:image 由页面按头像/兜底图生成
  const shareUrl = `${SITE_ORIGIN}/u/${encodeURIComponent(profile.username)}`;
  const shareTitle = `${profile.display_name}｜${t.brand.name}`;

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
        {profile.bio && <p className="pf-bio">{profile.bio}</p>}
        <div className="pf-meta">
          {jobTitle && (
            <span><IconUsers aria-hidden="true" />{jobTitle}</span>
          )}
          {profile.location && (
            <span><IconPin aria-hidden="true" />{profile.location}</span>
          )}
          {profile.website && (
            // 个人网址（用户自填的外部链接）由本人填写，新窗口打开且不传递权重；
            // 与下方「主页短链」是两个地址，图标用 IconHome 与分享动作区分
            <span className="pf-website">
              <IconHome aria-hidden="true" />
              <a href={profile.website} target="_blank" rel="noopener nofollow">
                {websiteLabel(profile.website)}
              </a>
            </span>
          )}
          {profile.orcid && (
            <span className="pf-orcid mono">ORCID {profile.orcid}</span>
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
        {profile.is_me && (
          // 主页短链行：展示 + 复制 + 分享（复制 28px 图标钮；分享 ghost 图标钮，
          // Toast 反馈）。短址 = SITE_ORIGIN/u/{username}，展示时省略协议。
          <div className="pf-url">
            <span className="pf-url-text mono">{shareUrl.replace(/^https:\/\//, "")}</span>
            <CopyButton value={shareUrl} ariaLabel={t.me.profileCopyLabel} />
            <ShareButton url={shareUrl} title={shareTitle} iconOnly variant="ghost" size="sm" ariaLabel={t.me.profileShareLabel} feedback="toast" />
          </div>
        )}
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
            {/* 分享主页：与主人态同一单形态 */}
            <ShareButton url={shareUrl} title={shareTitle} label={t.user.shareProfile} variant="secondary" size="md" ariaLabel={t.me.profileShareLabel} feedback="toast" />
          </>
        )}
      </div>
    </header>
  );
}
