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
 *    ko 한국어 / de Deutsch), 不随界面语言翻译; 无国旗/无地球图标
 *  - 触发器视觉 = ghost sm 文字按钮（顶栏右侧，DESIGN_SYSTEM 2.3）
 *  - /samelabs/* 下不渲染(路径检测, 该区域不在 locale 治理范围)
 *  - locale 列表复用 SUPPORTED_LOCALES, 不建第二份
 *  - query 直接取当前路由状态(useSearchParams), 无挂载后快照 ——
 *    客户端搜索导航后切换语言携带的是当前 query, 而非初始 URL 的
 */

import { useEffect, useRef } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { SUPPORTED_LOCALES, isPathAtOrBelow, replaceLocalePrefix, rewriteNextParam, type Locale } from "@/lib/localePath";

/** 各语言自称(固定, 不翻译) */
const NATIVE_NAMES: Record<string, string> = {
  "zh-CN": "简体中文",
  en: "English",
  ja: "日本語",
  ko: "한국어",
  de: "Deutsch",
};

export function LanguageSwitcher() {
  const t = useDictionary();
  const locale = useLocale();
  const pathname = usePathname() ?? "/";
  const searchParams = useSearchParams();
  const search = searchParams.toString();
  // BX-A6：next 回跳参数里的语言前缀同步换成目标语言 —— 登录页切语言后
  // 登录成功必须落在所选语言，而不是跳回旧语言的 next。
  const suffixFor = (target: Locale) => {
    const rewritten = rewriteNextParam(search, target);
    return rewritten ? `?${rewritten}` : "";
  };
  const detailsRef = useRef<HTMLDetailsElement>(null);

  // Esc 关闭浮层（IX-10），焦点回触发器。
  // SMK-006 / HGS-LOCALE-HOOK-01：所有 Hook 必须在下面的条件 return 之前 ——
  // 站点顶栏跨 /samelabs 与公开页常驻，条件 return 早于 Hook 会在客户端
  // 路由切换时改变 Hook 调用数量，触发 React Rules of Hooks 崩溃。
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key !== "Escape") return;
      const el = detailsRef.current;
      if (el?.open) {
        el.open = false;
        el.querySelector("summary")?.focus();
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // samelabs 后台不在 locale 治理范围(边界语义: /samelabs 与 /samelabs/*, 不含 /samelabs-guide 等)
  if (isPathAtOrBelow(pathname, "/samelabs")) return null;

  return (
    <details className="lang-switcher" aria-label={t.nav.languageSwitcher} ref={detailsRef}>
      <summary>{NATIVE_NAMES[locale] ?? locale}</summary>
      <div className="lang-switcher-menu" role="menu">
        {SUPPORTED_LOCALES.map((l) => (
          <a
            key={l}
            role="menuitem"
            hrefLang={l}
            href={replaceLocalePrefix(pathname, l) + suffixFor(l)}
            aria-current={l === locale ? "true" : undefined}
            className={l === locale ? "current" : undefined}
            onClick={() => {
              // Round 14: 匿名用户语言偏好改由语言切换器在客户端主动切换时写入
              document.cookie = `site_locale=${encodeURIComponent(l)}; path=/; max-age=31536000; SameSite=Lax`;
              if (detailsRef.current) {
                detailsRef.current.open = false;
              }
            }}
          >
            {NATIVE_NAMES[l] ?? l}
          </a>
        ))}
      </div>
    </details>
  );
}
