"use client";

import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

/**
 * SiteFooter — 全站唯一页脚（DESIGN_SYSTEM 2.3）。
 * 所有公开页和状态页共用；手机（≤640）同样显示并让位底栏
 * （shell.css：margin-bottom = --tabbar-clear），法务三页链接可达。
 */
export function SiteFooter() {
  const t = useDictionary();
  const locale = useLocale();
  return (
    <footer className="sh-footer">
      <span>
        {t.nav.footer}：<a href="mailto:mail@huagongshe.com" className="sh-footer-link">mail@huagongshe.com</a>
      </span>
      <span>
        {t.nav.footerAi}
        <a href="/llms.txt" className="sh-footer-link">llms.txt</a>
        {" · "}
        <Link href={withLocale("/mcp-guide", locale)} className="sh-footer-link">
          {t.nav.footerMcpGuide}
        </Link>
      </span>
      <span>
        <Link href={withLocale("/privacy", locale)} className="sh-footer-link">{t.nav.footerPrivacy}</Link>
        {" · "}
        <Link href={withLocale("/terms", locale)} className="sh-footer-link">{t.nav.footerTerms}</Link>
        {" · "}
        <Link href={withLocale("/support", locale)} className="sh-footer-link">{t.nav.footerSupport}</Link>
      </span>
    </footer>
  );
}
