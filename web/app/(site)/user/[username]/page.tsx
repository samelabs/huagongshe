import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import Link from "next/link";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { ProfileTabs } from "@/components/profile/ProfileTabs";
import { RetryNotice } from "@/components/profile/RetryNotice";
import { FollowButton } from "@/components/shared/FollowButton";
import { Avatar } from "@/components/ui/Avatar";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Tag } from "@/components/ui/Tag";
import { apiGet, isApiNotFound, reactionSvgUrl } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag } from "@/lib/alternates";
import { noteHeadline } from "@/lib/noteHeadline";

type Profile = {
  id: number; username: string; display_name: string; bio: string | null;
  avatar_url: string | null; created_at: string;
  location: string | null; institution: string | null; title: string | null;
  website: string | null; orcid: string | null;
  followers: number; following: number; public_reactions: number;
  is_following: boolean; is_followed_by: boolean; is_mutual: boolean; is_me: boolean;
  /* HGS-ACCOUNT-CONTENT-01（PM 裁定）: 停用账号主页不再 404 ——
     is_active=false 时仅渲染停用态卡片（无关注/分享/内容列表）。 */
  is_active?: boolean;
};
type Reaction = { id: number; reaction_smiles: string; followers: number; updated_at: string };
type NoteCard = { id: number; content: string; visibility: string; updated_at: string; chemical_ids: number[]; reaction_ids: number[] };
type NotesBlock = { items: NoteCard[]; total: number };

const REACTIONS_PAGE_SIZE = 20;

export async function generateMetadata({ params }: { params: Promise<{ username: string }> }): Promise<Metadata> {
  const { username } = await params;
  const canonical = `/user/${encodeURIComponent(username)}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    title: t.user.title.replace("{username}", username),
    description: t.user.desc,
    alternates: localeAlternates(canonical, locale),
    openGraph: { url: withLocale(canonical, locale), title: `${t.user.title.replace("{username}", username)}｜${t.brand.name}`, description: t.user.desc, locale: ogLocaleTag(locale) },
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
  const hasSession = (await cookies()).has("hgs_session");
  const headers = hasSession ? { Cookie: (await cookies()).toString() } : undefined;
  let profile: Profile;
  try { profile = await apiGet<Profile>(`/users/${encodeURIComponent(username)}`, headers); }
  catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  /* ── 停用态（4.1 / 6.11 状态页）：头像 + 名字 + Tag「账号已停用」+ 事实说明。
     不显示关注、分享和内容列表（列表接口对停用用户本就 404）；
     已公开的反应/笔记/技能在各自详情页保留可见并带「已停用」标记。 ── */
  if (profile.is_active === false) {
    const joined = new Date(profile.created_at).toLocaleDateString(locale);
    return <div className="content-page profile-page">
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
    </div>;
  }

  /* 正文数据：反应分页（tab=reactions）；笔记第一页 8 条（计数 + tab=notes 列表）。
     两个区块失败互不影响（RetryNotice），粉丝预览失败只影响右栏叠放（退化为人数）。 */
  let reactions: Reaction[] = [];
  let reactionsUnavailable = false;
  try { reactions = await apiGet<Reaction[]>(`/users/${encodeURIComponent(username)}/reactions?page=${page}&page_size=${REACTIONS_PAGE_SIZE}`); }
  catch { reactionsUnavailable = true; }

  let notesBlock: NotesBlock | null = null;
  let notesUnavailable = false;
  try { notesBlock = await apiGet<NotesBlock>(`/users/${encodeURIComponent(username)}/notes?page=1&page_size=8`); }
  catch { notesUnavailable = true; }

  /* 反应卡收藏初始态：登录时取已收藏反应 id 集（失败按空集处理，乐观更新兜底） */
  let favoredReactionIds = new Set<number>();
  if (hasSession) {
    try {
      // FX-8a（SMK-011 / HGS-PROFILE-FAVOR-SSR-01）：SSR 预取转发会话 Cookie，
      // 否则永远按匿名渲染为未收藏，首击发出重复 POST
      const followed = await apiGet<{ items: { id: number }[] }>(`/users/me/follows/reactions?page=1&page_size=100`, headers);
      favoredReactionIds = new Set(followed.items.map((item) => item.id));
    } catch { /* 保持空集 */ }
  }

  const notesTotal = notesUnavailable ? undefined : (notesBlock?.total ?? 0);
  const base = withLocale(`/user/${encodeURIComponent(profile.username)}`, locale);
  const joined = new Date(profile.created_at).toLocaleDateString(locale);

  return <div className="content-page profile-page">
    <Breadcrumb
      items={[
        { label: t.chemical.home, href: withLocale("/", locale) },
        { label: profile.display_name || profile.username },
      ]}
      ariaLabel={t.common.breadcrumb}
    />
    <ProfileHeader profile={{
      id: profile.id, username: profile.username, display_name: profile.display_name,
      bio: profile.bio, avatar_url: profile.avatar_url, created_at: profile.created_at,
      institution: profile.institution, title: profile.title,
      followers: profile.followers, following: profile.following,
      public_reactions: profile.public_reactions, notes: notesTotal ?? 0,
      is_following: profile.is_following, is_followed_by: profile.is_followed_by,
      is_mutual: profile.is_mutual, is_me: profile.is_me,
    }} />

    <ProfileTabs username={profile.username} tab={tab} reactionCount={profile.public_reactions} noteCount={notesTotal} />

    <div className="pf-body">
      <div className="pf-main">
        {/* ── 反应 tab：两列卡片（手机一列），分页沿用 page 参数 ── */}
        {tab === "reactions" && (reactionsUnavailable ? <RetryNotice>{t.user.contentError}</RetryNotice> : reactions.length ? (
          <>
            <div className="pf-rx-grid">
              {reactions.map((item) => (
                <article className="pf-rx-card" key={item.id}>
                  <Link className="pf-rx-eq" href={withLocale(`/reaction/${item.id}`, locale)}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={reactionSvgUrl(item.id, 720, 180)} alt={t.reaction.equationAlt(item.id)} loading="lazy" />
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
        ))}

        {/* ── 笔记 tab：标题 + 两行摘要 + 关联徽标 xs + 日期，点击进详情。
            R6/P2 源码契约（tests/test_p1c_*）：加载失败 ≠ total=0 —— 失败渲染
            错误态（Notice err + 重试），成功且 total>0 才渲染列表 DOM，
            total=0 只渲染 tab 空状态（下方 EmptyState）。 ── */}
        {tab === "notes" && notesUnavailable && (
          <RetryNotice>{t.notes.profileLoadFailed}</RetryNotice>
        )}
        {tab === "notes" && !notesUnavailable && notesBlock && notesBlock.total > 0 && (
          <div className="pf-note-list">
            {notesBlock.items.map((note) => (
              <Link className="pf-note-card" key={note.id} href={withLocale(`/note/${note.id}`, locale)}>
                <div className="pf-note-head">
                  <h3>{noteHeadline(note.content) || t.notes.detailTitle}</h3>
                  <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time>
                </div>
                <p className="pf-note-summary">{note.content}</p>
                {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
                  <div className="pf-note-refs">
                    {note.chemical_ids.slice(0, 3).map((cid) => <EntityBadge key={`c${cid}`} kind="chemical" id={cid} size="xs" ariaLabel={t.common.hcidLabel(cid)} />)}
                    {note.reaction_ids.slice(0, 3).map((rid) => <EntityBadge key={`r${rid}`} kind="reaction" id={rid} size="xs" ariaLabel={t.common.hridLabel(rid)} />)}
                  </div>
                )}
              </Link>
            ))}
          </div>
        )}
        {tab === "notes" && !notesUnavailable && notesBlock && notesBlock.total === 0 && (
          <EmptyState
            title={profile.is_me ? t.user.emptyNotesSelf : t.user.emptyNotesVisitor}
            action={profile.is_me ? { label: t.notes.writeNote, href: withLocale("/aichem?tab=notes&new=1", locale) } : undefined}
          />
        )}
      </div>
    </div>
  </div>;
}
