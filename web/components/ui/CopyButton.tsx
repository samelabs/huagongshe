"use client";

/**
 * CopyButton — 复制按钮（DESIGN_SYSTEM 3.5）。
 *
 * 只有一种尺寸：28 × 28，图标 16，手机上可点区域 44。
 * 行内使用时 inline-flex，对齐文字，不独占一行。
 * 复制成功：图标换 ✓ 保持 1.5s，并弹 Toast「已复制」（Toast 区域负责读屏播报）；
 * 失败弹 Toast 并选中文本便于手动复制。
 * 写剪贴板走 lib/clipboard（含非安全上下文的退路）。
 */
import { useRef, useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { IconCheck, IconCopy } from "./icons";
import { useToast } from "./Toast";
import { copyText } from "@/lib/clipboard";

const DONE_MS = 1500;

function selectElementText(el: HTMLElement | null) {
  if (!el) return;
  const range = document.createRange();
  range.selectNodeContents(el);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

export function CopyButton({ value, ariaLabel, textRef, className }: {
  /** 要写入剪贴板的文本 */
  value: string;
  /** 无障碍名称（如「复制 SMILES」）；缺省用字典 common.copy */
  ariaLabel?: string;
  /** clipboard 失败时选中文本的元素（如 CodeField 的 <code>） */
  textRef?: React.RefObject<HTMLElement | null>;
  className?: string;
}) {
  const t = useDictionary();
  const toast = useToast();
  const [done, setDone] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function copy() {
    const ok = await copyText(value);
    if (ok) toast.success(t.common.copied);
    else {
      selectElementText(textRef?.current ?? null);
      toast.error(t.common.copyFailed);
    }
    if (timer.current) clearTimeout(timer.current);
    setDone(ok);
    timer.current = setTimeout(() => setDone(false), DONE_MS);
  }

  return (
    <span className="hg-copy-wrap">
      <button
        type="button"
        className={["hg-copy", done ? "done" : "", className ?? ""].filter(Boolean).join(" ")}
        aria-label={ariaLabel ?? t.common.copy}
        onClick={() => void copy()}
      >
        <IconCopy className="cp" />
        <IconCheck className="ck" />
      </button>
    </span>
  );
}
