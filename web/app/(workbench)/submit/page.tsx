import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/workbench/SubmissionForm";
import { apiGet } from "@/lib/api.server";
import type { User } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { TextLink } from "@/components/ui/TextLink";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  // 与 /aichem 一致的边界 — 个人工作流页面不进索引(匿名 307 已缓解, 纯 SEO 卫生)
  return { title: t.submit.title, robots: { index: false, follow: false } };
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
    <div className="wb-grid">
      <div className="wb-grid-main">
        <section>
          <div className="wb-panel-head">
            <div>
              <h2>{editing ? t.submit.editTitle : t.submit.newTitle}</h2>
              <span>{editing ? t.submit.editDesc : t.submit.newDesc}</span>
            </div>
            <TextLink href={withLocale("/guide", locale)}>{t.submit.guideLink}</TextLink>
          </div>
          <Suspense><SubmissionForm /></Suspense>
        </section>
      </div>
    </div>
  );
}
