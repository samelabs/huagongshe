"use client";

import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import t from "@/lib/i18n";
import { DashboardEmpty, Pagination, PanelError, PanelHeading, PanelLoading } from "../shared";
import type { LoadState, NoticeResponse } from "../types";

export function ActivityPanel({ notices, state, page }: {
  notices: NoticeResponse;
  state: LoadState;
  page: number;
}) {
  return (
    <section>
      <PanelHeading title={t.me.tabActivity} subtitle={t.me.activityHint} />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError />}
      {state === "ready" && (notices.items.length
        ? <div className="wb-notice-list">
            {notices.items.map((item) => (
              <Link href={`/reaction/${item.reaction_id}`} key={item.id}>
                <span><strong>{t.me.activityActor(item.actor_display_name || t.me.activityActorFallback)}</strong><small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></span>
                <EntityId kind="reaction" id={item.reaction_id} compact />
              </Link>
            ))}
          </div>
        : <DashboardEmpty text={t.me.emptyActivity} />)}
      {state === "ready" && notices.total > notices.page_size && (
        <Pagination page={page} pageSize={notices.page_size} total={notices.total} href={(value) => `/aichem?tab=activity${value > 1 ? `&page=${value}` : ""}`} />
      )}
    </section>
  );
}
