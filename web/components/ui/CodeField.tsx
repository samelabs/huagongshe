"use client";

/**
 * CodeField — 等宽代码字段 + 复制按钮（参考 §6）。SMILES / InChIKey / Key
 * 等长标识的展示与复制；clipboard 失败时选中文本退回。
 */
import { useRef } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { CopyButton } from "./CopyButton";

export function CodeField({ value, copyLabel, className }: {
  value: string;
  /** 复制按钮的无障碍名称（如「复制 SMILES」） */
  copyLabel?: string;
  className?: string;
}) {
  const t = useDictionary();
  const codeRef = useRef<HTMLElement>(null);
  return (
    <div className={["hg-code", className ?? ""].filter(Boolean).join(" ")}>
      <code ref={codeRef}>{value}</code>
      <CopyButton value={value} ariaLabel={copyLabel ?? `${t.common.copy}`} textRef={codeRef} />
    </div>
  );
}
