import type { ReactNode } from "react";

/**
 * Section — 分区（版式基准）：分区标题 + 说明 + 内容。
 * 分区间距与标题到内容的间距都是 token（--sp-section / --sp-section-gap，
 * 手机档自动降档）。标题即 h2，不用独立 eyebrow。
 */
export function Section({
  title,
  description,
  children,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`hg-section${className ? ` ${className}` : ""}`}>
      <h2 className="hg-section-title">{title}</h2>
      {description != null && (
        <p className="hg-section-desc">{description}</p>
      )}
      <div className="hg-section-body">{children}</div>
    </section>
  );
}
