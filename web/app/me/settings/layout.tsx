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
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) redirect("/login?next=/me/settings");

  return <div className="content-page wb-page">
    <div className="wb">
      <div className="wb-bar">
        <div className="wb-bar-avatar">
          {user.avatar_url
            ? <img src={user.avatar_url} alt="" />
            : <span>{user.display_name.slice(0, 1)}</span>}
        </div>
        <div className="wb-bar-info">
          <strong>{user.display_name}</strong>
          <span>@{user.username}</span>
        </div>
        <div className="wb-bar-actions">
          <a className="wb-btn wb-btn-primary" href="/submit">{t.me.newReaction}</a>
          <a className="wb-btn wb-btn-ghost" href="/aichem">{t.me.title}</a>
        </div>
      </div>
      <div className="wb-body">
        <SettingsNav />
        <main className="wb-main">{children}</main>
      </div>
    </div>
  </div>;
}
