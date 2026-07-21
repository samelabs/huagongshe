import type { Metadata } from "next";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import { FollowButton } from "@/components/FollowButton";
import { PersonList, type PersonSummary } from "@/components/PersonList";
import { apiGet, isApiNotFound, reactionSvgUrl } from "@/lib/api";

type Profile = { id: number; username: string; display_name: string; bio: string | null; avatar_url: string | null; followers: number; following: number; public_reactions: number; is_following: boolean; is_me: boolean };
type Reaction = { id: number; reaction_smiles: string; followers: number; updated_at: string };
type PeopleResponse = { items: PersonSummary[]; total: number; page: number; page_size: number };
type PublicTab = "reactions" | "following" | "followers";

export async function generateMetadata({ params }: { params: Promise<{ username: string }> }): Promise<Metadata> {
  const { username } = await params;
  return { title: `@${username}`, description: "化工社用户主页" };
}

export default async function UserPage({ params, searchParams }: { params: Promise<{ username: string }>; searchParams: Promise<{ tab?: string | string[]; page?: string | string[] }> }) {
  const { username } = await params;
  const query = await searchParams;
  const requested = query.tab;
  const activeTab: PublicTab = requested === "following" || requested === "followers" ? requested : "reactions";
  const requestedPage = typeof query.page === "string" ? Number.parseInt(query.page, 10) : 1;
  const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
  const cookie = (await cookies()).toString();
  const headers = cookie ? { Cookie: cookie } : undefined;
  let profile: Profile;
  try { profile = await apiGet<Profile>(`/users/${encodeURIComponent(username)}`, 0, headers); }
  catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  let reactions: Reaction[] = [];
  let people: PeopleResponse = { items: [], total: 0, page: 1, page_size: 40 };
  let contentUnavailable = false;
  try {
    if (activeTab === "reactions") reactions = await apiGet<Reaction[]>(`/users/${encodeURIComponent(username)}/reactions?page=${page}&page_size=20`);
    else people = await apiGet<PeopleResponse>(`/users/${encodeURIComponent(username)}/${activeTab}?page=${page}&page_size=40`, 0, headers);
  } catch { contentUnavailable = true; }

  const base = `/user/${encodeURIComponent(profile.username)}`;
  return <div className="content-page public-profile-page">
    <header className="profile-header public-profile-header social-profile-header">
      <div className="profile-avatar">{profile.avatar_url ? <img src={profile.avatar_url} alt="" /> : profile.display_name.slice(0, 1)}</div>
      <div className="profile-primary"><p>@{profile.username}</p><h1>{profile.display_name}</h1>{profile.bio && <p className="profile-bio">{profile.bio}</p>}
        <div className="profile-counts profile-count-links">
          <Link className={activeTab === "reactions" ? "active" : ""} href={base}><strong>{profile.public_reactions}</strong><span>公开反应</span></Link>
          <Link className={activeTab === "following" ? "active" : ""} href={`${base}?tab=following`}><strong>{profile.following}</strong><span>关注</span></Link>
          <Link className={activeTab === "followers" ? "active" : ""} href={`${base}?tab=followers`}><strong>{profile.followers}</strong><span>粉丝</span></Link>
        </div>
      </div>
      <div className="public-profile-action">{profile.is_me
        ? <Link className="button secondary" href="/me">进入个人中心</Link>
        : <FollowButton endpoint={`/api/users/${encodeURIComponent(profile.username)}/follow`} initial={profile.is_following} count={profile.followers} showCount={false} />}
      </div>
    </header>

    <nav className="profile-tabs public-profile-tabs" aria-label="公开主页内容">
      <Link className={activeTab === "reactions" ? "active" : ""} href={base}>公开反应 <em>{profile.public_reactions}</em></Link>
      <Link className={activeTab === "following" ? "active" : ""} href={`${base}?tab=following`}>关注 <em>{profile.following}</em></Link>
      <Link className={activeTab === "followers" ? "active" : ""} href={`${base}?tab=followers`}>粉丝 <em>{profile.followers}</em></Link>
    </nav>

    <section className="dashboard-section public-profile-content">
      <div className="dashboard-panel-heading"><div><h2>{activeTab === "reactions" ? "公开反应" : activeTab === "following" ? "关注的人" : "粉丝"}</h2></div>{!contentUnavailable && <strong>{activeTab === "reactions" ? profile.public_reactions : people.total} {activeTab === "reactions" ? "条" : "人"}</strong>}</div>
      {contentUnavailable ? <div className="dashboard-empty"><p>内容暂时无法加载，请稍后重试。</p></div> : activeTab === "reactions" && (reactions.length ? <div className="repository-grid">{reactions.map((item) => <article key={item.id}>
        <header><Link href={`/reaction/${item.id}`}><EntityId kind="reaction" id={item.id} compact /></Link><span>{item.followers} 人关注</span></header>
        <Link className="repository-scheme" href={`/reaction/${item.id}`}><img loading="lazy" src={reactionSvgUrl(item.id, 720, 180)} alt={`HRID ${item.id}`} /></Link>
      </article>)}</div> : <div className="dashboard-empty"><p>还没有公开反应。</p></div>)}
      {!contentUnavailable && activeTab === "reactions" && profile.public_reactions > 20 && <nav className="profile-pagination" aria-label="分页">
        {page > 1 ? <Link href={page === 2 ? base : `${base}?page=${page - 1}`}>上一页</Link> : <span />}
        <small>{page} / {Math.ceil(profile.public_reactions / 20)}</small>
        {page * 20 < profile.public_reactions ? <Link href={`${base}?page=${page + 1}`}>下一页</Link> : <span />}
      </nav>}
      {!contentUnavailable && activeTab !== "reactions" && <PersonList items={people.items} empty={activeTab === "following" ? "还没有关注用户。" : "还没有粉丝。"} />}
      {!contentUnavailable && activeTab !== "reactions" && people.total > people.page_size && <nav className="profile-pagination" aria-label="分页">
        {page > 1 ? <Link href={`${base}?tab=${activeTab}&page=${page - 1}`}>上一页</Link> : <span />}
        <small>{page} / {Math.ceil(people.total / people.page_size)}</small>
        {page * people.page_size < people.total ? <Link href={`${base}?tab=${activeTab}&page=${page + 1}`}>下一页</Link> : <span />}
      </nav>}
    </section>
  </div>;
}
