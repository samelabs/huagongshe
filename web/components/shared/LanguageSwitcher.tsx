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
 *  - 浮层回收走站内统一规则(useDismissableMenu): 外部点击、焦点移出、
 *    Esc、路由变化
 */

import { usePathname, useSearchParams } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { Button } from "@/components/ui/Button";
import { SUPPORTED_LOCALES, isPathAtOrBelow, replaceLocalePrefix, rewriteNextParam, type Locale } from "@/lib/localePath";
import { useDismissableMenu } from "@/lib/useDismissableMenu";

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
  const menu = useDismissableMenu();

  // samelabs 后台不在 locale 治理范围(边界语义: /samelabs 与 /samelabs/*, 不含 /samelabs-guide 等)
  if (isPathAtOrBelow(pathname, "/samelabs")) return null;

  return (
    <div className={menu.open ? "lang-switcher open" : "lang-switcher"} ref={menu.rootRef} onKeyDown={menu.onKeyDown}>
      <Button
        variant="ghost"
        size="sm"
        ref={menu.triggerRef}
        aria-label={t.nav.languageSwitcher}
        aria-haspopup="menu"
        aria-expanded={menu.open}
        onClick={() => menu.setOpen((v) => !v)}
        className="lang-switcher-trigger"
      >
        {NATIVE_NAMES[locale] ?? locale}
      </Button>
      {menu.open && (
        <div className="lang-switcher-menu" role="menu">
          {SUPPORTED_LOCALES.map((l) => (
            <a
              key={l}
              role="menuitem"
              data-menu-item
              hrefLang={l}
              href={replaceLocalePrefix(pathname, l) + suffixFor(l)}
              aria-current={l === locale ? "true" : undefined}
              className={l === locale ? "current" : undefined}
              onClick={() => {
                // Round 14: 匿名用户语言偏好改由语言切换器在客户端主动切换时写入
                document.cookie = `site_locale=${encodeURIComponent(l)}; path=/; max-age=31536000; SameSite=Lax`;
                menu.setOpen(false);
              }}
            >
              {NATIVE_NAMES[l] ?? l}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
