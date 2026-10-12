"use client";

/**
 * AiSubmissionPrompt — 指南页的 AI 提交提示词（Step 11 §9.6）：
 * CodeField multiline + CopyButton（IX-7 复制播报/✓ 1.5s），不再手写 clipboard。
 */
import { useDictionary } from "@/components/shared/I18nContext";
import { CodeField } from "@/components/ui/CodeField";

export function AiSubmissionPrompt() {
  const t = useDictionary();
  return <CodeField value={t.guide.aiPrompt} copyLabel={t.guide.copyPrompt(false)} multiline />;
}
