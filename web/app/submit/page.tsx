import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/SubmissionForm";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.submit.title };
export default async function SubmitPage({ searchParams }: { searchParams: Promise<{ reaction?: string | string[] }> }) {
  const query = await searchParams;
  const editing = typeof query.reaction === "string" && /^\d+$/.test(query.reaction);
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">{t.submit.kicker}</p><h1>{editing ? t.submit.editTitle : t.submit.newTitle}</h1><p>{editing ? t.submit.editDesc : t.submit.newDesc}</p><Link className="text-button" href="/guide">{t.submit.guideLink}</Link></header><Suspense><SubmissionForm /></Suspense></div>;
}
