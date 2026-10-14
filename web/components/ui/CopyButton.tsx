"use client";

/**
 * CopyButton — 复制按钮（DESIGN_SYSTEM 3.5）。
 *
 * 只有一种尺寸：28 × 28，图标 16，手机上可点区域 44。
 * 行内使用时 inline-flex，对齐文字，不独占一行。
 * 复制成功：图标换 ✓ 保持 1.5s，aria-live 播报「已复制」。
 */
import { useRef, useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { IconCheck, IconCopy } from "./icons";

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
  const [done, setDone] = useState(false);
  const [announce, setAnnounce] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function copy() {
    let ok = false;
    try {
      await navigator.clipboard.writeText(value);
      ok = true;
    } catch {
      selectElementText(textRef?.current ?? null);
    }
    if (timer.current) clearTimeout(timer.current);
    setDone(ok);
    setAnnounce(ok ? t.common.copied : t.common.copyFailed);
    timer.current = setTimeout(() => {
      setDone(false);
      setAnnounce("");
    }, DONE_MS);
  }

  return (
    <span className="hg-copy-wrap">
      <span className="hg-sr" role="status" aria-live="polite">{announce}</span>
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
