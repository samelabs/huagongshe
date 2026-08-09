import Link from "next/link";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { WorkbenchNav } from "@/components/dashboard/WorkbenchNav";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import type { Summary } from "@/components/dashboard/types";
import t from "@/lib/i18n";

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

async function getSummary(cookieHeader: string): Promise<Summary | null> {
  try {
    return await apiGet<Summary>("/users/me/dashboard", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function WorkbenchLayout({ children }: { children: React.ReactNode }) {
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) redirect("/login?next=/aichem");
  const summary = cookieHeader ? await getSummary(cookieHeader) : null;
  const counts = summary?.counts ?? null;
  return (
    <div className="content-page wb-page">
      <div className="wb">
        <div className="wb-bar">
          <div className="wb-bar-avatar">
            {(summary?.avatar_url || user.avatar_url)
              ? <img src={summary?.avatar_url || user.avatar_url || ""} alt="" />
              : <span>{(summary?.display_name || user.display_name).slice(0, 1)}</span>}
          </div>
          <div className="wb-bar-info">
            <strong>{summary?.display_name || user.display_name}</strong>
            <span>@{summary?.username || user.username}</span>
          </div>
          <div className="wb-bar-actions">
            <Link className="wb-btn wb-btn-primary" href="/submit">{t.me.newReaction}</Link>
            <Link className="wb-btn wb-btn-ghost" href="/me/settings/api-tokens">{t.me.aiAssistant}</Link>
            <Link className="wb-btn wb-btn-ghost" href="/">{t.nav.home}</Link>
          </div>
        </div>
        <div className="wb-body">
          <Suspense><WorkbenchNav counts={counts} /></Suspense>
          <main className="wb-main">{children}</main>
        </div>
      </div>
    </div>
  );
}
