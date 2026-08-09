import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/SubmissionForm";
import { WorkbenchNav } from "@/components/dashboard/WorkbenchNav";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import type { Summary } from "@/components/dashboard/types";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.submit.title };

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

export default async function SubmitPage({ searchParams }: { searchParams: Promise<{ reaction?: string | string[] }> }) {
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) redirect("/login?next=/submit");
  const summary = cookieHeader ? await getSummary(cookieHeader) : null;
  const counts = summary?.counts ?? null;

  const query = await searchParams;
  const editing = typeof query.reaction === "string" && /^\d+$/.test(query.reaction);
  return <div className="content-page wb-page">
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
          <a className="wb-btn wb-btn-ghost" href="/aichem">{t.me.title}</a>
        </div>
      </div>
      <div className="wb-body">
        <WorkbenchNav counts={counts} />
        <main className="wb-main">
          <header className="page-title"><p className="page-kicker">{t.submit.kicker}</p><h1>{editing ? t.submit.editTitle : t.submit.newTitle}</h1><p>{editing ? t.submit.editDesc : t.submit.newDesc}</p><Link className="text-button" href="/guide">{t.submit.guideLink}</Link></header>
          <Suspense><SubmissionForm /></Suspense>
        </main>
      </div>
    </div>
  </div>;
}
