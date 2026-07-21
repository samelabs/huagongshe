import Link from "next/link";

export type PersonSummary = {
  username: string;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
};

export function PersonList({ items, empty }: { items: PersonSummary[]; empty: string }) {
  if (!items.length) return <div className="dashboard-empty"><p>{empty}</p></div>;
  return <div className="people-list">{items.map((person) => (
    <article className="person-row" key={person.username}>
      <Link className="person-avatar" href={`/user/${encodeURIComponent(person.username)}`} aria-label={`查看 ${person.display_name} 的主页`}>
        {person.avatar_url ? <img src={person.avatar_url} alt="" /> : person.display_name.slice(0, 1)}
      </Link>
      <div className="person-summary">
        <Link href={`/user/${encodeURIComponent(person.username)}`}>
          <strong>{person.display_name}</strong>
          <span>@{person.username}</span>
        </Link>
        {person.bio && <p>{person.bio}</p>}
      </div>
      <Link className="person-open" href={`/user/${encodeURIComponent(person.username)}`}>查看主页</Link>
    </article>
  ))}</div>;
}
