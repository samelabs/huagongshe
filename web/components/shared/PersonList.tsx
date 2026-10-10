"use client";

import Link from "next/link";
import { FollowButton } from "@/components/shared/FollowButton";
import { Avatar } from "@/components/ui/Avatar";
import { Tag } from "@/components/ui/Tag";
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

/** 关注/粉丝列表行（§6 Step 9 Part B.5）：Avatar 40 + 名字 + @username +
 *  简介首行 + 关注按钮（未关注 tonal / 已关注 secondary，hover 显示
 *  「取消关注」）+ 关系标签。粉丝列表里的人按定义都关注了当前用户：
 *  is_following → 「互相关注」，否则「关注了你」（列表语义可客户端判定，
 *  不需要 API 补字段；「我的关注」列表的互相关注需要 per-person
 *  is_followed_by，v1.7 不新增 API，暂不显示）。 */
export function PersonList({ items, kind, onFollowChange }: {
  items: PersonSummary[];
  kind: "followers" | "following";
  onFollowChange: (person: PersonSummary, following: boolean) => void;
}) {
  const t = useDictionary();
  const locale = useLocale();
  return <div className="wb-person-list">{items.map((person) => (
    <article className="wb-person-row" key={person.username}>
      <Link className="wb-person-avatar" href={withLocale(`/user/${encodeURIComponent(person.username)}`, locale)} aria-label={`${t.follow.viewProfile} ${person.display_name}`}>
        <Avatar id={person.username} name={person.display_name} src={person.avatar_url} size={40} />
      </Link>
      <div className="wb-person-info">
        <Link className="wb-person-id" href={withLocale(`/user/${encodeURIComponent(person.username)}`, locale)}>
          <strong>{person.display_name}</strong>
          <span>@{person.username}</span>
        </Link>
        {person.bio && <p className="wb-person-bio">{person.bio.split("\n")[0]}</p>}
      </div>
      {kind === "followers" && !person.is_me && (
        <Tag tone={person.is_following ? "blue" : undefined}>
          {person.is_following ? t.follow.mutual : t.follow.followsYou}
        </Tag>
      )}
      <div className="wb-person-actions">
        {!person.is_me && <FollowButton
          endpoint={`/users/${encodeURIComponent(person.username)}/follow`}
          initial={person.is_following}
          showCount={false}
          variant={person.is_following ? "secondary" : "tonal"}
          size="sm"
          idleText={kind === "followers" ? t.follow.followBack : t.follow.follow}
          activeText={t.follow.following}
          activeHoverText={t.follow.unfollow}
          onChange={(following) => onFollowChange(person, following)}
        />}
      </div>
    </article>
  ))}</div>;
}
