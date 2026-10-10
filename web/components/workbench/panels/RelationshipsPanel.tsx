"use client";

import { useEffect, useRef, useState } from "react";
import { PersonList, type PersonSummary } from "@/components/shared/PersonList";
import { useAccount } from "@/components/shared/AccountContext";
import { EmptyState } from "@/components/ui/EmptyState";
import { IconUser, IconUsers } from "@/components/ui/icons";
import { apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Pagination, PanelError, PanelHeading, PanelLoading } from "../shared";
import type { LoadState, PageResponse, PanelProps } from "../types";

const emptyPage = (): PageResponse<PersonSummary> => ({ items: [], total: 0, page: 1, page_size: 40 });

export function RelationshipsPanel({ kind, page, initialData, username }: PanelProps & {
  kind: "followers" | "following";
  initialData?: PageResponse<PersonSummary> | null;
  username?: string;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const { user } = useAccount();
  const targetUser = username || user?.username;
  const [data, setData] = useState<PageResponse<PersonSummary>>(initialData ?? emptyPage());
  const [state, setState] = useState<LoadState>(initialData ? "ready" : "loading");
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current && initialData) { mounted.current = true; return; }
    if (!targetUser) return;
    mounted.current = true;
    let active = true;
    setState("loading");
    setError(null);
    apiGet<PageResponse<PersonSummary>>(`/users/${encodeURIComponent(targetUser)}/${kind}?page=${page}&page_size=40`)
      .then((value) => { if (active) { setData(value); setState("ready"); } })
      .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    return () => { active = false; };
  }, [targetUser, kind, page]);

  function onFollowChange(person: PersonSummary, following: boolean) {
    setData((current) => ({
      ...current,
      items: kind === "following" && !following
        ? current.items.filter((item) => item.username !== person.username)
        : current.items.map((item) => item.username === person.username ? { ...item, is_following: following } : item),
      total: kind === "following" && !following ? Math.max(current.total - 1, 0) : current.total,
    }));
  }

  const title = kind === "followers" ? t.me.tabFollowers : t.me.tabFollowing;

  return (
    <section className="wb-panel">
      <PanelHeading title={title} subtitle={kind === "followers" ? t.me.followersHint : t.me.followingHint} count={state === "ready" ? data.total : "—"} unit={t.me.unitPerson} />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && (data.items.length ? (
        <PersonList items={data.items} kind={kind} onFollowChange={onFollowChange} />
      ) : (
        <EmptyState
          icon={kind === "followers" ? <IconUser /> : <IconUsers />}
          title={kind === "followers" ? t.me.emptyFollowers : t.me.emptyFollowing}
          action={{ label: t.nav.tabQuery, href: withLocale("/search", locale) }}
        />
      ))}
      {state === "ready" && data.total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => withLocale(`/aichem?tab=${kind}${value > 1 ? `&page=${value}` : ""}`, locale)} />
      )}
    </section>
  );
}
