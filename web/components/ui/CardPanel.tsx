import type { ReactNode } from "react";

/**
 * CardPanel — 卡片（版式基准）：1px 边框、--r-md 圆角、--pad-card 内边距，
 * 不加阴影（浮层才允许阴影，见 tokens.css --shadow-float）。
 */
export function CardPanel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`hg-card-panel${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}
