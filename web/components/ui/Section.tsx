import type { ReactNode } from "react";

/**
 * Section — 分区（版式基准）：分区标题 + 说明 + 内容。
 * 分区间距与标题到内容的间距都是 token（--sp-section / --sp-section-gap，
 * 手机档自动降档）。标题即 h2，不用独立 eyebrow。
 * action：分区级动作（该分区业务入口的按钮/链接），渲染在标题行最右；
 * 有 action 时标题与注记收进同一左簇，无 action 时 DOM 与历来一致。
 * title 可省略：head 三件套（title/note/action）全空时标题行不渲染 ——
 * 分区语义已由上游承载的场景不再重复标题（IX-12：不重复标题；如公开主页
 * Tabs 自带计数与选中态，其下内容分区不再挂同名 h2）。
 */
export function Section({
  id,
  title,
  note,
  description,
  action,
  children,
  className,
}: {
  /** 锚点 id（页内导航 / TOC 寻址） */
  id?: string;
  /** 分区标题（h2）；省略时若无 note/action 则不渲染标题行 */
  title?: ReactNode;
  /** 分区标题行的右侧注记（如计数），弱化排版 */
  note?: ReactNode;
  description?: ReactNode;
  /** 分区标题行的分区级动作（按钮/链接） */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const hasHead = title != null || note != null || action != null;
  return (
    <section id={id} className={`hg-section${className ? ` ${className}` : ""}`}>
      {hasHead && (
        <div className="hg-section-head">
          {action != null ? (
            <>
              <div className="hg-section-lead">
                <h2 className="hg-section-title">{title}</h2>
                {note != null && <div className="hg-section-note">{note}</div>}
              </div>
              <div className="hg-section-action">{action}</div>
            </>
          ) : (
            <>
              {title != null && <h2 className="hg-section-title">{title}</h2>}
              {note != null && <div className="hg-section-note">{note}</div>}
            </>
          )}
        </div>
      )}
      {description != null && (
        <p className="hg-section-desc">{description}</p>
      )}
      <div className="hg-section-body">{children}</div>
    </section>
  );
}
