"use client";

import { usePathname } from "next/navigation";
import { UrlTabs, type UrlTabItem } from "@/components/UrlTabs";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale, stripLocalePrefix } from "@/lib/localePath";

/**
 * 设置页 Tabs（DESIGN_SYSTEM 6.8 /)：
 * 个人资料 / 头像 / 账号安全 / AI Key
 * 链接与键盘交互基于 ui/Tabs（UrlTabs 包装）。
 */
export function SettingsTabs() {
  const t = useDictionary();
  const locale = useLocale();
  const pathname = usePathname();
  const routePath = stripLocalePrefix(pathname ?? "");

  let value = "profile";
  if (routePath.includes("/avatar")) value = "avatar";
  else if (routePath.includes("/security")) value = "security";
  else if (routePath.includes("/api-tokens")) value = "api-tokens";

  const tabs: readonly UrlTabItem[] = [
    { id: "profile", label: t.settings.nav.profile, href: withLocale("/me/settings/profile", locale) },
    { id: "avatar", label: t.settings.nav.avatar, href: withLocale("/me/settings/avatar", locale) },
    { id: "security", label: t.settings.nav.security, href: withLocale("/me/settings/security", locale) },
    { id: "api-tokens", label: t.settings.nav.tokens, href: withLocale("/me/settings/api-tokens", locale) },
  ];

  return (
    <UrlTabs
      tabs={tabs}
      value={value}
      ariaLabel={t.settings.title}
    />
  );
}
