"use client";

import { useDictionary } from "@/components/shared/I18nContext";

/**
 * SiteFooter — 全站唯一页脚（DESIGN_SYSTEM 2.3）。
 * 所有公开页和状态页共用。
 */
export function SiteFooter() {
  const t = useDictionary();
  return (
    <footer>
      <span>{t.nav.footer}：<a href="mailto:mail@huagongshe.com" className="footer-link">mail@huagongshe.com</a></span>
    </footer>
  );
}
