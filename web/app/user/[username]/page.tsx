import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import { FollowButton } from "@/components/FollowButton";
import { apiGet, isApiNotFound, reactionSvgUrl } from "@/lib/api";

type Profile = { id: number; username: string; display_name: string; bio: string | null; avatar_url: string | null; created_at: string; followers: number; following: number; public_reactions: number; is_following: boolean; is_followed_by: boolean; is_mutual: boolean; is_me: boolean };
type Reaction = { id: number; reaction_smiles: string; followers: number; updated_at: string };

export const revalidate = 3600;

export async function generateMetadata({ params }: { params: Promise<{ username: string }> }): Promise<Metadata> {
  const { username } = await params;
  return { title: `@${username}`, description: "化工社用户主页" };
}

export default async function UserPage({ params, searchParams }: { params: Promise<{ username: string }>; searchParams: Promise<{ page?: string | string[] }> }) {
  const { username } = await params;
  const query = await searchParams;
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  // Logged-in users get dynamic rendering for live follow state and is_me;
  // anonymous traffic hits the ISR cache.
  const hasSession = (await cookies()).has("hgs_session");
  const ttl = hasSession ? 0 : 3600;
  const headers = hasSession ? { Cookie: (await cookies()).toString() } : undefined;
  let profile: Profile;
  try { profile = await apiGet<Profile>(`/users/${encodeURIComponent(username)}`, ttl, headers); }
  catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  let reactions: Reaction[] = [];
  let contentUnavailable = false;
  try { reactions = await apiGet<Reaction[]>(`/users/${encodeURIComponent(username)}/reactions?page=${page}&page_size=20`, ttl); }
  catch { contentUnavailable = true; }

  const base = `/user/${encodeURIComponent(profile.username)}`;
  return <div className="content-page public-profile-page">
    <header className="profile-header public-profile-header social-profile-header">
      <div className="profile-avatar">{profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : profile.display_name.slice(0, 1)}</div>
      <div className="profile-primary">
        <h1>{profile.display_name}</h1>
        <p className="profile-username">@{profile.username}</p>
        {profile.bio && <p className="profile-bio">{profile.bio}</p>}
        <div className="profile-counts">
          <span><strong>{profile.following}</strong> 关注</span>
          <span><strong>{profile.followers}</strong> 粉丝</span>
        </div>
        <p className="profile-joined">加入时间：{new Date(profile.created_at).toLocaleDateString("zh-CN")}</p>
      </div>
      <div className="public-profile-action">
        {profile.is_me
          ? <Link className="button secondary" href="/me">个人中心</Link>
          : <>
            {profile.is_followed_by && !profile.is_following && <span className="follow-status-tag">关注了你</span>}
            {profile.is_mutual && <span className="follow-status-tag mutual">互相关注</span>}
            <FollowButton endpoint={`/api/users/${encodeURIComponent(profile.username)}/follow`} initial={profile.is_following} showCount={false} />
          </>}
      </div>
    </header>

    <section className="dashboard-section public-profile-content">
      <div className="dashboard-panel-heading"><div><h2>公开反应</h2></div>{!contentUnavailable && <strong>{profile.public_reactions} 条</strong>}</div>
      {contentUnavailable ? <div className="dashboard-empty"><p>内容暂时无法加载，请稍后重试。</p></div> : reactions.length ? <div className="repository-grid">{reactions.map((item) => <article key={item.id}>
        <header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link><span>{item.followers} 人收藏</span></header>
        <Link className="repository-scheme" href={`/reaction/${item.id}`}><img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link>
      </article>)}</div> : <div className="dashboard-empty"><p>还没有公开反应。</p></div>}
      {!contentUnavailable && profile.public_reactions > 20 && <nav className="profile-pagination" aria-label="分页">
        {page > 1 ? <Link href={page === 2 ? base : `${base}?page=${page - 1}`}>上一页</Link> : <span />}
        <small>{page} / {Math.ceil(profile.public_reactions / 20)}</small>
        {page * 20 < profile.public_reactions ? <Link href={`${base}?page=${page + 1}`}>下一页</Link> : <span />}
      </nav>}
    </section>
  </div>;
}
