import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
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

  return <main className="wb-settings-main">{children}</main>;
}
