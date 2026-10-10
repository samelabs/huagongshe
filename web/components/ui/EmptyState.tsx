"use client";

/**
 * EmptyState — 空状态（参考 §6，IX-8）：图标 + 一句标题 + 一句说明 + 一个
 * 下一步操作。禁止只写「暂无数据」。
 */
import type { ReactNode } from "react";
import { IconNote } from "./icons";
import { Button } from "./Button";

export function EmptyState({ icon, title, children, action }: {
  icon?: ReactNode;
  title: ReactNode;
  /** 一句说明（下一步指引） */
  children?: ReactNode;
  action?: { label: string; onClick?: () => void; href?: string };
}) {
  return (
    <div className="hg-empty">
      <div className="ic">{icon ?? <IconNote />}</div>
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action && (
        <Button variant="tonal" href={action.href} onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
