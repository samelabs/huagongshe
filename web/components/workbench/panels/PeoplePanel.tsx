"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Avatar } from "@/components/ui/Avatar";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Field";
import { IconUserSearch } from "@/components/ui/icons";
import { FollowButton } from "@/components/shared/FollowButton";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { apiGet } from "@/lib/api";
import { Pagination, PanelError, PanelHeading, PanelLoading, SlowNotice } from "../shared";
import type { LoadState } from "../types";

export type SearchUserItem = {
  id?: number;
  username: string;
  display_name: string;
  avatar_url: string | null;
  bio: string | null;
  follower_count: number;
  is_following: boolean;
  is_me?: boolean;
};

type SearchUserResponse = {
  users?: SearchUserItem[];
  items?: SearchUserItem[];
  total: number;
  page: number;
  page_size?: number;
  limit?: number;
};

export function PeoplePanel({
  page = 1,
  initialQuery = "",
}: {
  page?: number;
  initialQuery?: string;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const { user: currentUser } = useAccount();

  const [inputQuery, setInputQuery] = useState(initialQuery);
  const [submittedQuery, setSubmittedQuery] = useState(initialQuery);
  const [data, setData] = useState<SearchUserResponse>({ total: 0, page: 1, users: [] });
  const [state, setState] = useState<LoadState>(initialQuery.trim() ? "loading" : "idle");
  const [error, setError] = useState<unknown>(null);
  const latestLoad = useRef(0);

  async function searchUsers(q: string, targetPage: number) {
    const trimmed = q.trim();
    if (!trimmed) {
      setSubmittedQuery("");
      setData({ total: 0, page: 1, users: [] });
      setState("idle");
      return;
    }

    const requestId = ++latestLoad.current;
    setState("loading");
    setError(null);
    setSubmittedQuery(trimmed);

    try {
      const res = await apiGet<SearchUserResponse>(
        `/users/search?q=${encodeURIComponent(trimmed)}&page=${targetPage}&page_size=20`
      );
      if (requestId !== latestLoad.current) return;
      setData(res);
      setState("ready");
    } catch (err) {
      if (requestId !== latestLoad.current) return;
      setError(err);
      setState("error");
    }
  }

  useEffect(() => {
    if (initialQuery.trim()) {
      void searchUsers(initialQuery, page);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery, page]);

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = inputQuery.trim();
    if (!trimmed) {
      router.push(withLocale("/aichem?tab=people", locale));
      setSubmittedQuery("");
      setState("idle");
      return;
    }
    router.push(withLocale(`/aichem?tab=people&q=${encodeURIComponent(trimmed)}`, locale));
    void searchUsers(trimmed, 1);
  }

  function handleFollowChange(targetUsername: string, isFollowing: boolean) {
    setData((prev) => {
      const list = prev.users || prev.items || [];
      const updated = list.map((u) => {
        if (u.username === targetUsername) {
          const prevCount = u.follower_count ?? 0;
          return {
            ...u,
            is_following: isFollowing,
            follower_count: isFollowing ? prevCount + 1 : Math.max(0, prevCount - 1),
          };
        }
        return u;
      });
      return {
        ...prev,
        users: updated,
        items: updated,
      };
    });
  }

  const userList = data.users || data.items || [];
  const pageSize = data.page_size || data.limit || 20;

  return (
    <section className="wb-panel">
      <PanelHeading
        title={t.me.tabPeople}
        subtitle={t.me.peopleHint}
      />

      <form method="post" className="wb-search-form" onSubmit={handleSearchSubmit}>
        <div className="wb-search-field">
          <Input
            type="text"
            enterKeyHint="search"
            value={inputQuery}
            onChange={(e) => setInputQuery(e.target.value)}
            placeholder={t.me.peopleSearchPlaceholder}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            aria-label={t.me.tabPeople}
          />
          <Button type="submit" variant="primary">{t.me.homeSearchButton}</Button>
        </div>
      </form>

      {state === "idle" && (
        <EmptyState
          icon={<IconUserSearch />}
          title={t.me.peopleEmptyPrompt}
        >
          {t.me.peopleIdleDesc}
        </EmptyState>
      )}

      {state === "loading" && (
        <>
          <PanelLoading variant="list" />
          <SlowNotice active onRetry={() => void searchUsers(submittedQuery, page)} />
        </>
      )}

      {state === "error" && <PanelError error={error} />}

      {state === "ready" && submittedQuery && userList.length === 0 && (
        <EmptyState
          icon={<IconUserSearch />}
          title={t.me.peopleNoResults}
        />
      )}

      {state === "ready" && userList.length > 0 && (
        <div className="wb-person-list">
          {userList.map((person) => {
            const isMe = person.is_me || person.username === currentUser?.username;
            return (
              <article className="wb-person-row" key={person.username}>
                <Link
                  className="wb-person-avatar"
                  href={withLocale(`/user/${encodeURIComponent(person.username)}`, locale)}
                  aria-label={`${t.follow.viewProfile} ${person.display_name}`}
                >
                  <Avatar id={person.username} name={person.display_name} src={person.avatar_url} size={40} />
                </Link>
                <div className="wb-person-info">
                  <Link className="wb-person-id" href={withLocale(`/user/${encodeURIComponent(person.username)}`, locale)}>
                    <strong>{person.display_name}</strong>
                    <span>@{person.username}</span>
                  </Link>
                  {person.bio && <p className="wb-person-bio">{person.bio.split("\n")[0]}</p>}
                </div>
                <div className="wb-person-followers-tag">
                  <small>{t.me.peopleFollowers(person.follower_count ?? 0)}</small>
                </div>
                <div className="wb-person-actions">
                  {!isMe && (
                    <FollowButton
                      endpoint={`/users/${encodeURIComponent(person.username)}/follow`}
                      initial={person.is_following}
                      showCount={false}
                      variant={person.is_following ? "secondary" : "tonal"}
                      size="sm"
                      idleText={t.follow.follow}
                      activeText={t.follow.following}
                      activeHoverText={t.follow.unfollow}
                      onChange={(following) => handleFollowChange(person.username, following)}
                    />
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {state === "ready" && data.total > pageSize && (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={data.total}
          href={(val) => withLocale(`/aichem?tab=people&q=${encodeURIComponent(submittedQuery)}${val > 1 ? `&page=${val}` : ""}`, locale)}
        />
      )}
    </section>
  );
}
