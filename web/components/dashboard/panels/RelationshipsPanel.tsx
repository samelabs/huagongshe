"use client";

import { PersonList, type PersonSummary } from "@/components/PersonList";
import t from "@/lib/i18n";
import { DashboardEmpty, Pagination, PanelError, PanelHeading, PanelLoading } from "../shared";
import type { LoadState, PageResponse } from "../types";

export function RelationshipsPanel({ data, state, kind, page, onFollowChange }: {
  data: PageResponse<PersonSummary>;
  state: LoadState;
  kind: "followers" | "following";
  page: number;
  onFollowChange: (person: PersonSummary, following: boolean) => void;
}) {
  const title = kind === "followers" ? t.me.tabFollowers : t.me.tabFollowing;
  return (
    <section>
      <PanelHeading title={title} subtitle={kind === "followers" ? t.me.followersHint : t.me.followingHint} count={state === "ready" ? data.total : "—"} unit={t.me.unitPerson} />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError />}
      {state === "ready" && (
        <PersonList items={data.items} empty={kind === "followers" ? t.me.emptyFollowers : t.me.emptyFollowing} kind={kind} onFollowChange={onFollowChange} />
      )}
      {state === "ready" && data.total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => `/aichem?tab=${kind}${value > 1 ? `&page=${value}` : ""}`} />
      )}
    </section>
  );
}
