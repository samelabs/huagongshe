"use client";

/**
 * Toast — 全局轻提示（参考 §6，IX-2）。
 *
 * ToastProvider 挂在 app/layout.tsx；useToast() 提供
 *   toast.success(msg, { action: { label, onClick } })  3s 自动消失
 *   toast.error(msg)                                    手动关闭
 * 最多同时显示 3 条；底部居中，手机上避开 tabbar 与 safe-area（ui.css）。
 */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { useDictionary } from "@/components/shared/I18nContext";
import { IconOk, IconX } from "./icons";

const MAX_VISIBLE = 3;
const SUCCESS_MS = 3000;

export type ToastAction = { label: string; onClick: () => void };
type ToastKind = "ok" | "err";
type ToastItem = { id: number; kind: ToastKind; message: string; action?: ToastAction };

type ToastApi = {
  success: (message: string, opts?: { action?: ToastAction }) => void;
  error: (message: string) => void;
};

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const t = useDictionary();
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
  }, []);

  const push = useCallback((kind: ToastKind, message: string, action?: ToastAction) => {
    const id = ++seq.current;
    setItems((prev) => [...prev, { id, kind, message, action }].slice(-MAX_VISIBLE));
    if (kind === "ok") {
      timers.current.set(id, setTimeout(() => dismiss(id), SUCCESS_MS));
    }
  }, [dismiss]);

  const api = useRef<ToastApi>({
    success: (message, opts) => push("ok", message, opts?.action),
    error: (message) => push("err", message),
  });

  return (
    <ToastContext.Provider value={api.current}>
      {children}
      <div className="hg-toast-host" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className="hg-toast">
            {item.kind === "ok" ? <IconOk className="ok" /> : <IconX className="err" />}
            <span>{item.message}</span>
            {item.action && (
              <button
                type="button"
                onClick={() => {
                  item.action?.onClick();
                  dismiss(item.id);
                }}
              >
                {item.action.label}
              </button>
            )}
            {item.kind === "err" && (
              <button type="button" className="hg-toast-x" aria-label={t.common.close} onClick={() => dismiss(item.id)}>
                <IconX />
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
