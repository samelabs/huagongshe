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
 *  - query 直接取当前路由状态(useSearchParams), 无挂载后快照 ——
 *    客户端搜索导航后切换语言携带的是当前 query, 而非初始 URL 的
 */

import { usePathname, useSearchParams } from "next/navigation";
import { useLocale } from "@/components/shared/I18nContext";
import { SUPPORTED_LOCALES, isPathAtOrBelow, replaceLocalePrefix } from "@/lib/localePath";

/** 各语言自称(固定, 不翻译) */
const NATIVE_NAMES: Record<string, string> = {
  "zh-CN": "简体中文",
  en: "English",
  ja: "日本語",
  ko: "한국어",
  de: "Deutsch",
};

export function LanguageSwitcher() {
  const locale = useLocale();
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  const suffix = search ? `?${search}` : "";

  // samelabs 后台不在 locale 治理范围(边界语义: /samelabs 与 /samelabs/*, 不含 /samelabs-guide 等)
  if (isPathAtOrBelow(pathname, "/samelabs")) return null;

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
            href={replaceLocalePrefix(pathname, l) + suffix}
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
