"use client";

import Link from "next/link";
import { FollowButton } from "@/components/shared/FollowButton";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

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
  const t = useDictionary();
  const locale = useLocale();
  if (!items.length) return <div className="wb-empty"><p>{empty}</p></div>;
  return <div className="wb-person-list">{items.map((person) => (
    <article className="wb-person-row" key={person.username}>
      <Link className="wb-person-avatar" href={withLocale(`/user/${encodeURIComponent(person.username)}`, locale)} aria-label={t.follow.viewProfile + " " + person.display_name}>
        {person.avatar_url ? <img src={person.avatar_url} alt="" /> : person.display_name.slice(0, 1)}
      </Link>
      <div className="wb-person-info">
        <Link href={withLocale(`/user/${encodeURIComponent(person.username)}`, locale)}>
          <strong>{person.display_name}</strong>
          <span>@{person.username}</span>
        </Link>
        {person.bio && <p>{person.bio}</p>}
      </div>
      <div className="wb-person-actions">
        {!person.is_me && <FollowButton
          endpoint={`/users/${encodeURIComponent(person.username)}/follow`}
          initial={person.is_following}
          showCount={false}
          variant="secondary"
          size="sm"
          idleText={kind === "followers" ? t.follow.followBack : t.follow.follow}
          activeText={t.follow.unfollow}
          onChange={(following) => onFollowChange(person, following)}
        />}
      </div>
    </article>
  ))}</div>;
}
