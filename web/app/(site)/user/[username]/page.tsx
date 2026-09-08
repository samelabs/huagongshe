import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { FollowButton } from "@/components/shared/FollowButton";
import { apiGet, isApiNotFound, reactionSvgUrl } from "@/lib/api";
import t from "@/lib/i18n";

type Profile = {
  id: number; username: string; display_name: string; bio: string | null;
  avatar_url: string | null; created_at: string;
  location: string | null; institution: string | null; title: string | null;
  website: string | null; orcid: string | null;
  followers: number; following: number; public_reactions: number;
  is_following: boolean; is_followed_by: boolean; is_mutual: boolean; is_me: boolean;
};
type Reaction = { id: number; reaction_smiles: string; followers: number; updated_at: string };

export async function generateMetadata({ params }: { params: Promise<{ username: string }> }): Promise<Metadata> {
  const { username } = await params;
  const canonical = `/user/${encodeURIComponent(username)}`;
  return {
    title: t.user.title.replace("{username}", username),
    description: t.user.desc,
    alternates: { canonical },
    openGraph: { url: canonical, title: `${t.user.title.replace("{username}", username)}｜${t.brand.name}`, description: t.user.desc },
  };
}

export default async function UserPage({ params, searchParams }: { params: Promise<{ username: string }>; searchParams: Promise<{ page?: string | string[] }> }) {
  const { username } = await params;
  const query = await searchParams;
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const hasSession = (await cookies()).has("hgs_session");
  const headers = hasSession ? { Cookie: (await cookies()).toString() } : undefined;
  let profile: Profile;
  try { profile = await apiGet<Profile>(`/users/${encodeURIComponent(username)}`, headers); }
  catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  let reactions: Reaction[] = [];
  let contentUnavailable = false;
  try { reactions = await apiGet<Reaction[]>(`/users/${encodeURIComponent(username)}/reactions?page=${page}&page_size=20`); }
  catch { contentUnavailable = true; }

  const base = `/user/${encodeURIComponent(profile.username)}`;
  return <div className="content-page public-profile-page">
    <header className="profile-header public-profile-header social-profile-header">
      <div className="profile-avatar">{profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : profile.display_name.slice(0, 1)}</div>
      <div className="profile-primary">
        <h1>{profile.display_name}</h1>
        <p className="profile-username">@{profile.username}</p>
        {(profile.title || profile.institution) && (
          <p className="profile-title">{[profile.title, profile.institution].filter(Boolean).join(" · ")}</p>
        )}
        {profile.bio && <p className="profile-bio">{profile.bio}</p>}
        {(profile.location || profile.website || profile.orcid) && (
          <div className="profile-meta">
            {profile.location && <span>📍 {profile.location}</span>}
            {/* 0904 P1收口: 用户可控 URL 直作 href, javascript: 伪协议可点击执行 —
                加 http(s) 守卫(判据同 CasExternals.tsx 供应商站外链)。 */}
            {profile.website && /^https?:\/\//i.test(profile.website) && <a href={profile.website} target="_blank" rel="nofollow noopener noreferrer">{profile.website.replace(/^https?:\/\//i, "")}</a>}
            {profile.orcid && <a href={`https://orcid.org/${profile.orcid}`} target="_blank" rel="noreferrer">ORCID: {profile.orcid}</a>}
          </div>
        )}
        <div className="profile-social">
          <span className="profile-counts-inline">
            <strong>{profile.following}</strong> {t.user.following}
            <strong>{profile.followers}</strong> {t.user.followers}
          </span>
          {profile.is_me
            ? <Link className="profile-edit-link" href="/me/settings/profile">{t.user.editProfile}</Link>
            : <>
              {profile.is_followed_by && !profile.is_following && <span className="follow-status-tag">{t.user.followedBy}</span>}
              {profile.is_mutual && <span className="follow-status-tag mutual">{t.user.mutual}</span>}
              <FollowButton endpoint={`/users/${encodeURIComponent(profile.username)}/follow`} initial={profile.is_following} showCount={false} />
            </>}
        </div>
        <p className="profile-joined">{t.user.joinedAt(new Date(profile.created_at).toLocaleDateString("zh-CN"))}</p>
      </div>
    </header>

    <section className="wb-section public-profile-content">
      <div className="wb-panel-head"><div><h2>{t.user.publicReactions}</h2></div>{!contentUnavailable && <strong>{t.user.reactionCount(profile.public_reactions)}</strong>}</div>
      {contentUnavailable ? <div className="wb-empty"><p>{t.user.contentError}</p></div> : reactions.length ? <div className="repository-grid">{reactions.map((item) => <article key={item.id}>
        <header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link><span>{t.user.peopleCount(item.followers)}</span></header>
        <Link className="repository-scheme" href={`/reaction/${item.id}`}><img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={t.reaction.equationAlt(item.id)} /></Link>
      </article>)}</div> : <div className="wb-empty"><p>{t.user.noReactions}</p></div>}
      {!contentUnavailable && profile.public_reactions > 20 && <nav className="profile-pagination" aria-label={t.common.pageNav}>
        {page > 1 ? <Link href={page === 2 ? base : `${base}?page=${page - 1}`}>{t.common.prev}</Link> : <span />}
        <small>{t.common.pageOf(page, Math.ceil(profile.public_reactions / 20))}</small>
        {page * 20 < profile.public_reactions ? <Link href={`${base}?page=${page + 1}`}>{t.common.next}</Link> : <span />}
      </nav>}
    </section>
  </div>;
}
