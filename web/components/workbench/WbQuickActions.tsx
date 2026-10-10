"use client";

/**
 * WbQuickActions — 工作台「新建反应 / 新建笔记」快捷入口（Part D 临时安置）。
 *
 * v1.7 顶栏统一后，原工作台顶栏的两个创建入口迁到侧栏顶部（桌面）
 * 与抽屉顶部（手机）。Step 8 重做工作台时再调整位置。
 * primary = 新建反应（/submit），secondary = 新建笔记（/aichem?tab=notes&new=1）。
 */
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";

export function WbQuickActions() {
  const t = useDictionary();
  const locale = useLocale();
  return (
    <div className="wb-quick-actions">
      <Button variant="primary" size="sm" href={withLocale("/submit", locale)}>{t.me.navNewReaction}</Button>
      <Button variant="secondary" size="sm" href={withLocale("/aichem?tab=notes&new=1", locale)}>{t.me.navNewNote}</Button>
    </div>
  );
}
