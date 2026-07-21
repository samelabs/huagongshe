import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { EntityId } from "@/components/EntityId";
import { FollowButton } from "@/components/FollowButton";
import { apiGet, reactionSvgUrl } from "@/lib/api";
import Link from "next/link";

type Profile = { id: number; username: string; display_name: string; bio: string | null; avatar_url: string | null; followers: number; following: number; public_reactions: number; is_following: boolean; is_me: boolean };
type Reaction = { id: number; reaction_smiles: string; followers: number; updated_at: string };

export async function generateMetadata({ params }: { params: Promise<{ username: string }> }): Promise<Metadata> {
  const { username } = await params;
  try { const user = await apiGet<Profile>(`/users/${encodeURIComponent(username)}`, 300); return { title: user.display_name }; } catch { return { title: "用户" }; }
}

export default async function UserPage({ params }: { params: Promise<{ username: string }> }) {
  const { username } = await params;
  let profile: Profile; let reactions: Reaction[];
  const cookie = (await cookies()).toString();
  try {
    [profile, reactions] = await Promise.all([
      apiGet<Profile>(`/users/${encodeURIComponent(username)}`, 0, cookie ? { Cookie: cookie } : undefined),
      apiGet<Reaction[]>(`/users/${encodeURIComponent(username)}/reactions`),
    ]);
  } catch { notFound(); }
  return <div className="content-page public-profile-page">
    <header className="profile-header public-profile-header">
      <div className="profile-avatar">{profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : profile.display_name.slice(0, 1)}</div>
      <div><p>@{profile.username}</p><h1>{profile.display_name}</h1>{profile.bio && <p className="profile-bio">{profile.bio}</p>}<div className="profile-counts"><span><strong>{profile.public_reactions}</strong> 公开反应</span><span><strong>{profile.followers}</strong> 关注者</span><span><strong>{profile.following}</strong> 正在关注</span></div></div>
      {!profile.is_me && <FollowButton endpoint={`/api/users/${encodeURIComponent(profile.username)}/follow`} initial={profile.is_following} count={profile.followers} />}
    </header>
    <section className="dashboard-section"><div className="section-heading"><div><p>PUBLIC REPOSITORY</p><h2>公开反应</h2></div><span>{reactions.length} 条</span></div>{reactions.length ? <div className="repository-grid">{reactions.map((item) => <article key={item.id}><header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link><span>{item.followers} 人关注</span></header><Link className="repository-scheme" href={`/reaction/${item.id}`}><img src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link></article>)}</div> : <p className="quiet-empty">还没有公开反应。</p>}</section>
  </div>;
}
