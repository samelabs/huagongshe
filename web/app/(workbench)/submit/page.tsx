import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/workbench/SubmissionForm";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.submit.title };
}

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function SubmitPage({ searchParams }: { searchParams: Promise<{ reaction?: string | string[] }> }) {
  const h = await headers();
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) redirect(withLocale(`/login?next=${encodeURIComponent("/submit")}`, locale));

  const query = await searchParams;
  const editing = typeof query.reaction === "string" && /^\d+$/.test(query.reaction);
  return (
    <section>
      <div className="wb-panel-head">
        <div>
          <h2>{editing ? t.submit.editTitle : t.submit.newTitle}</h2>
          <span>{editing ? t.submit.editDesc : t.submit.newDesc}</span>
        </div>
        <Link className="text-button" href={withLocale("/guide", locale)}>{t.submit.guideLink}</Link>
      </div>
      <Suspense><SubmissionForm /></Suspense>
    </section>
  );
}
