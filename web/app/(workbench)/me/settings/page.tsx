import { redirect } from "next/navigation";
import { headers } from "next/headers";
import { getRequestLocale } from "@/lib/serverI18n";
import { splitLocalePrefix, withLocale } from "@/lib/localePath";

export default async function SettingsPage() {
  const originalPath = (await headers()).get("x-site-locale-path");
  // 带 locale 前缀访问时保持前缀跳转; 直接访问保持既有无前缀路径
  if (originalPath && splitLocalePrefix(originalPath.split("?")[0])) {
    redirect(withLocale("/me/settings/profile", await getRequestLocale()));
  }
  redirect("/me/settings/profile");
}
