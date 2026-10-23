import type { Metadata } from "next";
import { cache } from "react";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import Link from "next/link";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { ProfileTabs } from "@/components/profile/ProfileTabs";
import { RetryNotice } from "@/components/profile/RetryNotice";
import { FollowButton } from "@/components/shared/FollowButton";
import { Avatar } from "@/components/ui/Avatar";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { PageFrame } from "@/components/ui/PageFrame";
import { Section } from "@/components/ui/Section";
import { Tag } from "@/components/ui/Tag";
import { apiGet } from "@/lib/api.server";
import { isApiNotFound, reactionSvgUrl } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeCanonical, ogLocaleTag, SITE_ORIGIN } from "@/lib/alternates";
import { buildShareMetadata } from "@/lib/shareMeta";
import { noteListPresentation } from "@/lib/noteHeadline";
import { reactionTitleText, type TitledParticipant } from "@/lib/reactionTitle";

type Profile = {
  id: number; username: string; display_name: string; bio: string | null;
  avatar_url: string | null; created_at: string;
  location: string | null; institution: string | null; title: string | null;
  website: string | null; orcid: string | null;
  followers: number; following: number; public_reactions: number;
  is_following: boolean; is_followed_by: boolean; is_mutual: boolean; is_me: boolean;
  /* 停用账号主页不再 404 ——
     active=false 时仅渲染停用态卡片（无关注/分享/内容列表）。 */
  active?: boolean;
};
type Reaction = {
  id: number; reaction_smiles: string; followers: number; updated_at: string;
  /* 参与物投影（与详情接口同形状）：卡片标题按「主反应物 → 主产物」解析 */
  participants?: TitledParticipant[];
};
type NoteCard = { id: number; slug: string; content: string; visibility: string; updated_at: string; chemical_ids: number[]; reaction_ids: number[] };
type NotesBlock = { items: NoteCard[]; total: number };

const REACTIONS_PAGE_SIZE = 20;
const NOTES_PAGE_SIZE = 8;

/** 同请求内 metadata 与页面体共享的同一次取数（此前各拉一次后端，
 * cookie 内置 —— metadata 与页面看到同一份 is_me 投影）。 */
const loadProfile = cache(async (username: string): Promise<Profile> => {
  const cookieStore = await cookies();
  const headers = cookieStore.has("hgs_session") ? { Cookie: cookieStore.toString() } : undefined;
  return apiGet<Profile>(`/users/by-username/${encodeURIComponent(username)}`, headers);
});

export async function generateMetadata({ params }: { params: Promise<{ username: string }> }): Promise<Metadata> {
  const { username } = await params;
  const canonical = `/user/${encodeURIComponent(username)}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  // og:image 用头像（512×512 方图，api 上传管线固定产 512 变体）；无头像退全局兜底横版品牌图
  const profile = await loadProfile(username).catch(() => null);
  const hasAvatar = Boolean(profile?.avatar_url);
  const pageTitle = `${profile?.display_name ?? username}｜${t.brand.name}`;
  const shareMeta = buildShareMetadata({
    title: pageTitle,
    description: t.user.desc,
    path: canonical,
    locale,
    siteName: t.brand.name,
    ogImage: hasAvatar
      ? { url: `${SITE_ORIGIN}${profile!.avatar_url}`, width: 512, height: 512, alt: pageTitle }
      : { url: "/og.png", width: 1200, height: 630, alt: t.brand.ogAlt },
    twitterCard: hasAvatar ? "summary" : "summary_large_image",
  });
  return {
    title: `${profile?.display_name ?? username}`,
    description: t.user.desc,
    alternates: localeCanonical(canonical, locale),
    ...shareMeta,
  };
}

export default async function UserPage({ params, searchParams }: { params: Promise<{ username: string }>; searchParams: Promise<{ tab?: string | string[]; page?: string | string[] }> }) {
  const { username } = await params;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const query = await searchParams;
  const tab = query.tab === "notes" ? "notes" : "reactions";
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  let profile: Profile;
  try { profile = await loadProfile(username); }
  catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  /* ── 停用态（4.1 / 6.11 状态页）：头像 + 名字 + Tag「账号已停用」+ 事实说明。
     不显示关注、分享和内容列表（列表接口对停用用户本就 404）；
     已公开的反应/笔记/技能在各自详情页保留可见并带「已停用」标记。 ── */
  if (profile.active === false) {
    const joined = new Date(profile.created_at).toLocaleDateString(locale);
    return <PageFrame className="profile-page">
      <div className="pf-deactivated">
        <Avatar id={profile.username} name={profile.display_name || profile.username} src={profile.avatar_url} size={80} />
        <div className="pf-deactivated-id">
          <h1>{profile.display_name || profile.username}</h1>
          <p className="pf-deactivated-handle">@{profile.username}</p>
          <Tag tone="neutral" dot>{t.user.deactivatedTag}</Tag>
        </div>
      </div>
      <EmptyState title={t.user.deactivatedTitle}>{t.user.deactivatedBody}</EmptyState>
      <p className="pf-deactivated-joined">{t.user.joinedAt(joined)}</p>
    </PageFrame>;
  }

  /* 正文数据：反应与笔记各自分页（共用 page 参数，同一时刻只渲染一个 tab）；
     笔记计数 + tab=notes 列表。
     两个区块失败互不影响（RetryNotice），粉丝预览失败只影响右栏叠放（退化为人数）。 */
  let reactions: Reaction[] = [];
  let reactionsUnavailable = false;
  try { reactions = await apiGet<Reaction[]>(`/users/${encodeURIComponent(username)}/reactions?page=${page}&page_size=${REACTIONS_PAGE_SIZE}`); }
  catch { reactionsUnavailable = true; }

  let notesBlock: NotesBlock | null = null;
  let notesUnavailable = false;
  try { notesBlock = await apiGet<NotesBlock>(`/users/${encodeURIComponent(username)}/notes?page=${page}&page_size=${NOTES_PAGE_SIZE}`); }
  catch { notesUnavailable = true; }

  /* 反应卡收藏初始态：登录访客取自己的已收藏反应 id 集（失败按空集，乐观更新兜底） */
  let favoredReactionIds = new Set<number>();
  const cookieStore = await cookies();
  if (cookieStore.has("hgs_session")) {
    try {
      // SSR 预取转发会话 Cookie，
      // 否则永远按匿名渲染为未收藏，首击发出重复 POST
      const followed = await apiGet<{ items: { id: number }[] }>(`/users/me/follows/reactions?page=1&page_size=100`, { Cookie: cookieStore.toString() });
      favoredReactionIds = new Set(followed.items.map((item) => item.id));
    } catch { /* 保持空集 */ }
  }

  const notesTotal = notesUnavailable ? undefined : (notesBlock?.total ?? 0);
  const base = withLocale(`/user/${encodeURIComponent(profile.username)}`, locale);
  const joined = new Date(profile.created_at).toLocaleDateString(locale);

  /* 主页场景：名片区直接置顶（无面包屑），内容区随后。 */
  return <PageFrame className="profile-page">
    <ProfileHeader profile={{
      id: profile.id, username: profile.username, display_name: profile.display_name,
      bio: profile.bio, avatar_url: profile.avatar_url, created_at: profile.created_at,
      institution: profile.institution, title: profile.title,
      location: profile.location, website: profile.website, orcid: profile.orcid,
      followers: profile.followers, following: profile.following,
      public_reactions: profile.public_reactions, notes: notesTotal ?? 0,
      is_following: profile.is_following, is_followed_by: profile.is_followed_by,
      is_mutual: profile.is_mutual, is_me: profile.is_me,
    }} />

    <ProfileTabs username={profile.username} tab={tab} reactionCount={profile.public_reactions} noteCount={notesTotal} />

    {/* ── 笔记 tab：标题 + 两行摘要 + 关联徽标 xs + 日期，点击进详情。
        笔记是社交承载，排在反应之前（DESIGN_SYSTEM 6.6；手机默认落本 tab）。
        源码契约（tests/test_notes_ui.py）：加载失败 ≠ total=0 —— 失败渲染
        错误态（Notice err + 重试），成功且 total>0 才渲染列表 DOM，
        total=0 只渲染 tab 空状态（下方 EmptyState）。分区不挂标题（同反应 tab）── */}
    {tab === "notes" && (
      <Section className="pf-tab-body">
        {notesUnavailable && (
          <RetryNotice>{t.notes.profileLoadFailed}</RetryNotice>
        )}
        {!notesUnavailable && notesBlock && notesBlock.total > 0 && (
          <>
            <div className="pf-note-list">
              {notesBlock.items.map((note) => {
                const pres = noteListPresentation(note);
                return (
                  <Link className="pf-note-card" key={note.id} href={withLocale(`/note/${note.slug}`, locale)}>
                    <div className="pf-note-head">
                      {pres.title && <h3>{pres.title}</h3>}
                      <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time>
                    </div>
                    <p className="pf-note-summary">{pres.body}</p>
                    {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
                      <div className="pf-note-refs">
                        {note.chemical_ids.slice(0, 3).map((cid) => <EntityBadge key={`c${cid}`} kind="chemical" id={cid} size="xs" ariaLabel={t.common.hcidLabel(cid)} />)}
                        {note.reaction_ids.slice(0, 3).map((rid) => <EntityBadge key={`r${rid}`} kind="reaction" id={rid} size="xs" ariaLabel={t.common.hridLabel(rid)} />)}
                      </div>
                    )}
                  </Link>
                );
              })}
            </div>
            {notesBlock.total > NOTES_PAGE_SIZE && (
              <nav className="pf-pagination" aria-label={t.common.pageNav}>
                {page > 1
                  ? <Link className="hg-btn ghost sm" href={page === 2 ? `${base}?tab=notes` : `${base}?tab=notes&page=${page - 1}`}>{t.common.prev}</Link>
                  : <span className="hg-btn ghost sm" aria-disabled="true">{t.common.prev}</span>}
                <small className="pf-pagination-page">{t.common.pageOf(page, Math.ceil(notesBlock.total / NOTES_PAGE_SIZE))}</small>
                {page * NOTES_PAGE_SIZE < notesBlock.total
                  ? <Link className="hg-btn ghost sm" href={`${base}?tab=notes&page=${page + 1}`}>{t.common.next}</Link>
                  : <span className="hg-btn ghost sm" aria-disabled="true">{t.common.next}</span>}
              </nav>
            )}
          </>
        )}
        {!notesUnavailable && notesBlock && notesBlock.total === 0 && (
          <EmptyState
            title={profile.is_me ? t.user.emptyNotesSelf : t.user.emptyNotesVisitor}
            action={profile.is_me ? { label: t.notes.writeNote, href: withLocale("/aichem?tab=notes&new=1", locale) } : undefined}
          />
        )}
      </Section>
    )}

    {/* ── 反应 tab：两列卡片（手机一列），分页沿用 page 参数。
        分区不挂标题 —— Tabs 已带计数与选中态（不重复标题） ── */}
    {tab === "reactions" && (
      <Section className="pf-tab-body">
        {reactionsUnavailable ? <RetryNotice>{t.user.contentError}</RetryNotice> : reactions.length ? (
          <>
            <div className="pf-rx-grid">
              {reactions.map((item) => (
                <article className="pf-rx-card" key={item.id}>
                  <h3 className="pf-rx-title">
                    <Link href={withLocale(`/reaction/${item.id}`, locale)}>{reactionTitleText(item.participants ?? [], { t, locale, reactionId: item.id })}</Link>
                  </h3>
                  <Link className="pf-rx-eq" href={withLocale(`/reaction/${item.id}`, locale)}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={reactionSvgUrl(item.id)} alt={t.reaction.equationAlt(item.id)} loading="lazy" />
                  </Link>
                  <div className="pf-rx-foot">
                    <EntityBadge kind="reaction" id={item.id} size="md" href={withLocale(`/reaction/${item.id}`, locale)} ariaLabel={t.common.hridLabel(item.id)} />
                    <FollowButton
                      endpoint={`/reactions/${item.id}/follow`}
                      initial={favoredReactionIds.has(item.id)}
                      label="favor"
                      variant="ghost"
                      iconOnly
                      showCount={false}
                    />
                    <span className="pf-rx-meta">{t.user.peopleCount(item.followers)}</span>
                    {item.updated_at && <time className="pf-rx-meta" dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleDateString(locale)}</time>}
                  </div>
                </article>
              ))}
            </div>
            {profile.public_reactions > REACTIONS_PAGE_SIZE && (
              <nav className="pf-pagination" aria-label={t.common.pageNav}>
                {page > 1
                  ? <Link className="hg-btn ghost sm" href={page === 2 ? `${base}?tab=reactions` : `${base}?tab=reactions&page=${page - 1}`}>{t.common.prev}</Link>
                  : <span className="hg-btn ghost sm" aria-disabled="true">{t.common.prev}</span>}
                <small className="pf-pagination-page">{t.common.pageOf(page, Math.ceil(profile.public_reactions / REACTIONS_PAGE_SIZE))}</small>
                {page * REACTIONS_PAGE_SIZE < profile.public_reactions
                  ? <Link className="hg-btn ghost sm" href={`${base}?tab=reactions&page=${page + 1}`}>{t.common.next}</Link>
                  : <span className="hg-btn ghost sm" aria-disabled="true">{t.common.next}</span>}
              </nav>
            )}
          </>
        ) : (
          <EmptyState
            title={profile.is_me ? t.user.emptyReactionsSelf : t.user.emptyReactionsVisitor}
            action={profile.is_me ? { label: t.notes.createReaction, href: withLocale("/submit", locale) } : undefined}
          />
        )}
      </Section>
    )}
  </PageFrame>;
}
