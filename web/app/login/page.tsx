import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.auth.title };
export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const query = await searchParams;
  const nextPath = safeNextPath(typeof query.next === "string" ? query.next : null);
  return <div className="auth-page"><section className="auth-intro"><p className="page-kicker">{t.auth.kicker}</p><h1>{t.auth.loginTitle}</h1><p>{t.auth.intro}</p><ul>{t.auth.features.map((feature) => <li key={feature}>{feature}</li>)}</ul></section><section className="auth-panel"><AccountForm nextPath={nextPath} /></section></div>;
}

function safeNextPath(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/aichem";
}
