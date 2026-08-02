"use client";

import Link from "next/link";
import { FollowButton } from "@/components/FollowButton";
import t from "@/lib/i18n";

export type PersonSummary = {
  username: string;
  display_name: string;
  bio: string | null;
  avatar_url: string | null;
  is_following: boolean;
  is_me: boolean;
};

export function PersonList({ items, empty, kind, onFollowChange }: {
  items: PersonSummary[];
  empty: string;
  kind: "followers" | "following";
  onFollowChange: (person: PersonSummary, following: boolean) => void;
}) {
  if (!items.length) return <div className="dashboard-empty"><p>{empty}</p></div>;
  return <div className="people-list">{items.map((person) => (
    <article className="person-row" key={person.username}>
      <Link className="person-avatar" href={`/user/${encodeURIComponent(person.username)}`} aria-label={t.follow.viewProfile + " " + person.display_name}>
        {person.avatar_url ? <img src={person.avatar_url} alt="" /> : person.display_name.slice(0, 1)}
      </Link>
      <div className="person-summary">
        <Link href={`/user/${encodeURIComponent(person.username)}`}>
          <strong>{person.display_name}</strong>
          <span>@{person.username}</span>
        </Link>
        {person.bio && <p>{person.bio}</p>}
      </div>
      <div className="person-actions">
        <Link className="person-open" href={`/user/${encodeURIComponent(person.username)}`}>{t.follow.viewProfile}</Link>
        {!person.is_me && <FollowButton
          endpoint={`/api/users/${encodeURIComponent(person.username)}/follow`}
          initial={person.is_following}
          showCount={false}
          idleText={kind === "followers" ? t.follow.followBack : t.follow.follow}
          activeText={t.follow.unfollow}
          onChange={(following) => onFollowChange(person, following)}
        />}
      </div>
    </article>
  ))}</div>;
}
