import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { headers } from "next/headers";
import { getRequestLocale } from "@/lib/serverI18n";
import { withLocale, splitLocalePrefix } from "@/lib/localePath";

// HGS-A3-02: /me 是个人工作台入口(匿名 307 到登录), 与 /aichem 一致不进索引
export const metadata: Metadata = { robots: { index: false, follow: false } };

export default async function MePage() {
  const originalPath = (await headers()).get("x-site-locale-path");
  // 带 locale 前缀访问时保持前缀跳转; 直接访问保持既有无前缀路径
  // (前缀判定走唯一 parser splitLocalePrefix)
  if (originalPath && splitLocalePrefix(originalPath.split("?")[0])) {
    redirect(withLocale("/me/settings/profile", await getRequestLocale()));
  }
  redirect("/me/settings/profile");
}
