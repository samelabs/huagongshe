"use client";

/**
 * CodeField — 等宽代码字段 + 复制按钮（参考 §6）。SMILES / InChIKey / Key
 * 等长标识的展示与复制；clipboard 失败时选中文本退回。
 * Step 11（IX-7 / §9.6）：内容在字段内部横向滚动（页面不得横向滚动）；
 * multiline 用于多行配置（JSON / 提示词）——块状布局，纵向限高内部滚动。
 */
import { useRef } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { CopyButton } from "./CopyButton";

export function CodeField({ value, copyLabel, multiline, className }: {
  value: string;
  /** 复制按钮的无障碍名称（如「复制 SMILES」） */
  copyLabel?: string;
  /** 多行形态（JSON / 长提示词）：块状 + 内部滚动，不撑破布局 */
  multiline?: boolean;
  className?: string;
}) {
  const t = useDictionary();
  const codeRef = useRef<HTMLElement>(null);
  return (
    <div className={["hg-code", multiline ? "multiline" : "", className ?? ""].filter(Boolean).join(" ")}>
      <code ref={codeRef}>{value}</code>
      <CopyButton value={value} ariaLabel={copyLabel ?? `${t.common.copy}`} textRef={codeRef} />
    </div>
  );
}
