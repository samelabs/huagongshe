"use client";

/**
 * LanguageSwitcher · 公开语言切换器
 *
 * 行为: 只替换当前 URL 的 locale 前缀, pathname 其余段与 query 完整保留,
 * 直接导航到目标 locale URL —— 不经首页中转; cookie(site_locale)由 proxy
 * 在进入带前缀 URL 时同步写入(见 web/proxy.ts), 登录 cookie 不受影响。
 *
 * 规则:
 *  - 语言名称恒用各语言自称(zh-CN 简体中文 / en English / ja 日本語 /
 *    ko 한국어 / de Deutsch), 不随界面语言翻译
 *  - 无国旗
 *  - /samelabs/* 下不渲染(路径检测, 该区域不在 locale 治理范围)
 *  - locale 列表复用 SUPPORTED_LOCALES, 不建第二份
 *  - SSR 安全: pathname 用 usePathname(), query 挂载后从 location 读取
 */

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useLocale } from "@/components/shared/I18nContext";
import { SUPPORTED_LOCALES } from "@/lib/i18n/locales";

/** 各语言自称(固定, 不翻译) */
const NATIVE_NAMES: Record<string, string> = {
  "zh-CN": "简体中文",
  en: "English",
  ja: "日本語",
  ko: "한국어",
  de: "Deutsch",
};

/** 把当前带前缀路径换成目标 locale 前缀; 无前缀(内部直访)时加前缀 */
export function replaceLocalePrefix(pathname: string, next: string): string {
  const segments = pathname.split("/");
  if (segments.length > 1 && SUPPORTED_LOCALES.includes(segments[1] as never)) {
    segments[1] = next;
    return segments.join("/") || `/${next}`;
  }
  return `/${next}${pathname === "/" ? "" : pathname}`;
}

export function LanguageSwitcher() {
  const locale = useLocale();
  const pathname = usePathname() ?? "/";
  const [search, setSearch] = useState("");

  // query 只在 client 挂载后读取(避免 SSR/client 不一致)
  useEffect(() => { setSearch(window.location.search); }, []);

  // samelabs 后台不在 locale 治理范围
  if (pathname.startsWith("/samelabs")) return null;

  return (
    <details className="lang-switcher" aria-label="Language">
      <summary>
        <span aria-hidden="true">🌐</span>
        <span className="lang-switcher-current">{NATIVE_NAMES[locale] ?? locale}</span>
      </summary>
      <div className="lang-switcher-menu" role="menu">
        {SUPPORTED_LOCALES.map((l) => (
          <a
            key={l}
            role="menuitem"
            hrefLang={l}
            href={replaceLocalePrefix(pathname, l) + search}
            aria-current={l === locale ? "true" : undefined}
            className={l === locale ? "current" : undefined}
          >
            {NATIVE_NAMES[l] ?? l}
          </a>
        ))}
      </div>
    </details>
  );
}
