"use client";

import Link from "next/link";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

/**
 * SiteFooter — 全站唯一页脚（DESIGN_SYSTEM 2.3）。
 * 所有公开页和状态页共用。
 */
export function SiteFooter() {
  const t = useDictionary();
  const locale = useLocale();
  return (
    <footer>
      <span>
        {t.nav.footer}：<a href="mailto:mail@huagongshe.com" className="footer-link">mail@huagongshe.com</a>
      </span>
      <span className="footer-ai">
        {t.nav.footerAi}
        <a href="/llms.txt" className="footer-link">llms.txt</a>
        {" · "}
        <Link href={withLocale("/mcp-guide", locale)} className="footer-link">
          {t.nav.footerMcpGuide}
        </Link>
      </span>
    </footer>
  );
}
