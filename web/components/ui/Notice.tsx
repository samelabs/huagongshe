"use client";

/**
 * Notice — 页面级提示条（参考 §6，IX-2「页面级失败：Notice，附带重试」）。
 * info / ok / warn / err，可带一个操作按钮（如「重试」）。
 */
import type { ReactNode } from "react";
import { IconInfo, IconOk, IconWarn, IconX } from "./icons";
import { Button, type ButtonVariant } from "./Button";

export type NoticeTone = "info" | "ok" | "warn" | "err";

const ICONS: Record<NoticeTone, () => ReactNode> = {
  info: () => <IconInfo />,
  ok: () => <IconOk />,
  warn: () => <IconWarn />,
  err: () => <IconX />,
};

export function Notice({ tone = "info", title, children, action }: {
  tone?: NoticeTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: { label: string; onClick: () => void; variant?: ButtonVariant };
}) {
  return (
    <div
      className={["hg-notice", tone].filter(Boolean).join(" ")}
      role={tone === "err" || tone === "warn" ? "alert" : "status"}
    >
      {ICONS[tone]()}
      <div>
        {title && <strong>{title}</strong>}
        {children && <p>{children}</p>}
      </div>
      {action && (
        <Button variant={action.variant ?? "ghost"} size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
