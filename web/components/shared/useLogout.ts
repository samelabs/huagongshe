"use client";

import { useRouter } from "next/navigation";
import { useAccount } from "./AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { useToast } from "@/components/ui/Toast";
import { withLocale } from "@/lib/localePath";

/**
 * useLogout — 全站唯一的登出实现（FX-12 / HGS-LOGOUT-FAIL-01）。
 * 失败（500/网关）：Toast 报错、不清本地会话、不跳转 —— 绝不假装成功；
 * 成功：清账号上下文 → 回首页 → refresh。桌面头像菜单（SiteHeader UserMenu）
 * 与手机抽屉（WbMobileNav）共用，调用方负责先收起自己的浮层。
 */
export function useLogout(): () => Promise<void> {
  const router = useRouter();
  const toast = useToast();
  const { clear } = useAccount();
  const t = useDictionary();
  const locale = useLocale();

  return async function logout() {
    try {
      const res = await fetch("/api/auth/logout", { method: "POST" });
      if (!res.ok) throw new Error(`logout ${res.status}`);
    } catch {
      toast.error(t.nav.logoutFailed);
      return;
    }
    clear();
    router.push(withLocale("/", locale));
    router.refresh();
  };
}
