import type { ReactNode } from "react";

/**
 * Section — 分区（版式基准）：分区标题 + 说明 + 内容。
 * 分区间距与标题到内容的间距都是 token（--sp-section / --sp-section-gap，
 * 手机档自动降档）。标题即 h2，不用独立 eyebrow。
 */
export function Section({
  id,
  title,
  note,
  description,
  children,
  className,
}: {
  /** 锚点 id（页内导航 / TOC 寻址） */
  id?: string;
  title: ReactNode;
  /** 分区标题行的右侧注记（如计数），弱化排版 */
  note?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={`hg-section${className ? ` ${className}` : ""}`}>
      <div className="hg-section-head">
        <h2 className="hg-section-title">{title}</h2>
        {note != null && <div className="hg-section-note">{note}</div>}
      </div>
      {description != null && (
        <p className="hg-section-desc">{description}</p>
      )}
      <div className="hg-section-body">{children}</div>
    </section>
  );
}
