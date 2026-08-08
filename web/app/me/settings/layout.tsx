import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { SettingsNav } from "@/components/settings/SettingsNav";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: { default: t.settings.title, template: `%s · ${t.settings.title}` }, robots: { index: false, follow: false } };

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  const h = await headers();
  const user = await getUser(h.get("cookie"));
  if (!user) redirect("/login?next=/me/settings");

  return <div className="content-page settings-page">
    <header className="page-title settings-title"><p className="page-kicker">{t.settings.titleKicker}</p><h1>{t.settings.title}</h1><p>{t.settings.subtitle}</p></header>
    <div className="settings-layout"><SettingsNav /><div className="settings-content">{children}</div></div>
  </div>;
}
