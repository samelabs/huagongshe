"use client";

/**
 * ConfirmDialog — 不可逆操作的二次确认（参考 §6，IX-3 / IX-10）。
 *
 * ConfirmProvider 挂在 app/layout.tsx；useConfirm() 返回
 *   const ok = await confirm({ title, body, confirmLabel, tone: "danger" })
 *
 * 行为契约：role=alertdialog + aria-labelledby/describedby；焦点锁在弹窗内；
 * 默认焦点在「取消」；Esc / 点遮罩 = 取消；关闭后焦点回到触发元素；
 * 打开期间锁定 body 滚动。title 应为问句，body 写明对象名称与后果，
 * confirmLabel 写具体动作（由调用方按 IX-3 组织文案）。
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useDictionary } from "@/components/shared/I18nContext";
import { Button } from "./Button";

export type ConfirmOptions = {
  /** 问句，如「删除这条笔记？」 */
  title: ReactNode;
  /** 写明对象名称与后果 */
  body?: ReactNode;
  /** 具体动作，如「删除笔记」 */
  confirmLabel: ReactNode;
  cancelLabel?: string;
  /** 目前只有 danger；确认按钮用 danger 变体 */
  tone?: "danger";
};

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

export function useConfirm(): ConfirmFn {
  const ctx = useContext(ConfirmContext);
  if (!ctx) throw new Error("useConfirm must be used inside <ConfirmProvider>");
  return ctx;
}

const FOCUSABLE = "a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex='-1'])";

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const t = useDictionary();
  const [state, setState] = useState<{ options: ConfirmOptions; resolve: (ok: boolean) => void } | null>(null);
  const [mounted, setMounted] = useState(false);
  const openerRef = useRef<HTMLElement | null>(null);
  const backRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = "hg-confirm-title";
  const bodyId = "hg-confirm-body";

  useEffect(() => setMounted(true), []);

  const confirm = useCallback<ConfirmFn>((options) => {
    return new Promise<boolean>((resolve) => {
      openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      setState({ options, resolve });
    });
  }, []);

  const close = useCallback((ok: boolean) => {
    setState((current) => {
      current?.resolve(ok);
      return null;
    });
    const opener = openerRef.current;
    if (opener && document.contains(opener)) opener.focus();
    openerRef.current = null;
  }, []);

  // 打开期间：焦点进「取消」+ 锁定 body 滚动；卸载时恢复
  useEffect(() => {
    if (!state) return;
    cancelRef.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [state]);

  function trapTab(e: React.KeyboardEvent) {
    if (e.key !== "Tab" || !backRef.current) return;
    const nodes = Array.from(backRef.current.querySelectorAll<HTMLElement>(FOCUSABLE))
      .filter((el) => el.offsetParent !== null);
    if (nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      close(false);
      return;
    }
    trapTab(e);
  }

  const api = useRef<ConfirmFn>(confirm);

  return (
    <ConfirmContext.Provider value={api.current}>
      {children}
      {mounted && state && createPortal(
        <div
          className="hg-modal-back"
          ref={backRef}
          onMouseDown={(e) => { if (e.target === backRef.current) close(false); }}
          onKeyDown={onKeyDown}
        >
          <div
            className="hg-modal"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={state.options.body ? bodyId : undefined}
          >
            <h3 id={titleId}>{state.options.title}</h3>
            {state.options.body && <p id={bodyId}>{state.options.body}</p>}
            <footer>
              <button type="button" className="hg-btn secondary" ref={cancelRef} onClick={() => close(false)}>
                {state.options.cancelLabel ?? t.common.cancel}
              </button>
              <Button variant={state.options.tone === "danger" ? "danger" : "primary"} onClick={() => close(true)}>
                {state.options.confirmLabel}
              </Button>
            </footer>
          </div>
        </div>,
        document.body,
      )}
    </ConfirmContext.Provider>
  );
}
