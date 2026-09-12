import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";
import { SamelabsNav } from "@/components/SamelabsNav";
import { apiGet, type User } from "@/lib/api";
import t from "@/lib/i18n";

export const metadata: Metadata = {
  title: { default: t.admin.title, template: `%s · ${t.admin.title}` },
  robots: { index: false, follow: false },
};

/**
 * /samelabs/** 服务端封闭 (A1):
 * - 未登录 → redirect 登录页(不输出任何管理 HTML)
 * - 已登录非 admin → 不渲染管理 shell / 内部架构, 只给一行提示
 * - admin → 正常
 * 复用现有 session 机制(/users/me 返回 role), 不造第二套鉴权。
 */
async function getAdminUser(cookieHeader: string | null): Promise<User | null> {
  try {
    if (!cookieHeader) return null;
    return await apiGet<User>("/users/me", { cookie: cookieHeader });
  } catch {
    return null;
  }
}

export default async function SamelabsLayout({ children }: { children: React.ReactNode }) {
  const h = await headers();
  const user = await getAdminUser(h.get("cookie"));
  if (!user) redirect("/login?next=/samelabs");

  if (user.role !== "admin") {
    // 非 admin: 不渲染 SamelabsNav / 管理内容 —— 只有一行提示
    return <div className="content-page samelabs-page">
      <div className="notice error">{t.admin.noPermission}</div>
    </div>;
  }

  return <div className="content-page samelabs-page">
    <div className="admin-shell">
      <SamelabsNav />
      <div className="admin-content">{children}</div>
    </div>
  </div>;
}
