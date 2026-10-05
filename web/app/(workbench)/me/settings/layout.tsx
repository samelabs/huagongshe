import type { Metadata } from "next";
import { headers, headers as nextHeaders } from "next/headers";
import { redirect } from "next/navigation";
import { apiGet } from "@/lib/api";
import type { User } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale, splitLocalePrefix } from "@/lib/localePath";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: { default: t.settings.title, template: `%s · ${t.settings.title}` }, robots: { index: false, follow: false } };
}

async function getUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch { return null; }
}

export default async function SettingsLayout({ children }: { children: React.ReactNode }) {
  const h = await headers();
  const locale = await getRequestLocale();
  const cookieHeader = h.get("cookie");
  const user = await getUser(cookieHeader);
  if (!user) {
    // 前缀判定走唯一 parser splitLocalePrefix, 不再硬编码五语言 regex
    const originalPath = (await nextHeaders()).get("x-site-locale-path");
    if (originalPath && splitLocalePrefix(originalPath.split("?")[0])) {
      redirect(withLocale(`/login?next=${encodeURIComponent(originalPath)}`, locale));
    }
    redirect("/login?next=/me/settings");
  }

  return <div className="wb-panel">{children}</div>;
}
