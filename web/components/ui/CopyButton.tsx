"use client";

/**
 * CopyButton — 复制按钮（参考 §6，IX-7）。
 *
 * 复制成功：图标换 ✓ 保持 1.5s，aria-live 播报「已复制」。
 * clipboard 不可用/失败：退回到选中文本（textRef 指向的元素），
 * 播报「复制失败，请手动复制」，不显示 ✓。
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

export function CopyButton({ value, ariaLabel, mini, textRef, className }: {
  /** 要写入剪贴板的文本 */
  value: string;
  /** 无障碍名称（如「复制 SMILES」）；缺省用字典 common.copy */
  ariaLabel?: string;
  /** 22px 小尺寸（EntityBadge 旁） */
  mini?: boolean;
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
        className={["hg-copy", mini ? "mini" : "", done ? "done" : "", className ?? ""].filter(Boolean).join(" ")}
        aria-label={ariaLabel ?? t.common.copy}
        onClick={() => void copy()}
      >
        <IconCopy className="cp" />
        <IconCheck className="ck" />
      </button>
    </span>
  );
}
