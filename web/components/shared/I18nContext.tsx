"use client";

/**
 * I18nProvider · 轻量 client locale context
 *
 * Server → Client 只传 locale 字符串(字典含函数, 不作为 props 传递)。
 * useDictionary() 在 client 侧按当前 locale 调用现有 getDictionary(locale),
 * 复用同一份字典注册, 不复制字典、不建第二套 locale state。
 */

import { createContext, useContext, type ReactNode } from "react";

import { getDictionary } from "@/lib/i18n";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import type { Locale } from "@/lib/i18n/locales";

const LocaleContext = createContext<Locale | null>(null);

export function I18nProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

/** 当前请求 locale(由 root layout 从 x-site-locale 求得后传入 Provider) */
export function useLocale(): Locale {
  const locale = useContext(LocaleContext);
  if (locale === null) throw new Error("useLocale 必须在 <I18nProvider> 内使用");
  return locale;
}

/** 当前 locale 的字典(client 侧调用现有 getDictionary, 同一份注册) */
export function useDictionary(): Dictionary {
  return getDictionary(useLocale());
}
