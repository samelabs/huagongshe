import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/SubmissionForm";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.submit.title };

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function SubmitPage({ searchParams }: { searchParams: Promise<{ reaction?: string | string[] }> }) {
  const h = await headers();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) redirect("/login?next=/submit");

  const query = await searchParams;
  const editing = typeof query.reaction === "string" && /^\d+$/.test(query.reaction);
  return (
    <>
      <header className="page-head"><p className="page-kicker">{t.submit.kicker}</p><h1>{editing ? t.submit.editTitle : t.submit.newTitle}</h1><p>{editing ? t.submit.editDesc : t.submit.newDesc}</p><Link className="text-button" href="/guide">{t.submit.guideLink}</Link></header>
      <Suspense><SubmissionForm /></Suspense>
    </>
  );
}
