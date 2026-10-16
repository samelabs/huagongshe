import type { ReactNode } from "react";
import { Breadcrumb, type BreadcrumbItem } from "./Breadcrumb";

/**
 * PageHead — 页头（版式基准）：面包屑 + H1 + 副标题 + 操作区。
 *
 * H1 两档：default 28（列表/文章页）、hero 40（实体详情页）；
 * 字重恒 --fw-display，行高 --lh-tight。
 */
export function PageHead({
  breadcrumb,
  title,
  subtitle,
  meta,
  actions,
  hero = false,
  className,
}: {
  breadcrumb?: BreadcrumbItem[];
  title: ReactNode;
  subtitle?: ReactNode;
  /** 标题行的块级元信息（如作者署名），与纯文本副标题并列 */
  meta?: ReactNode;
  actions?: ReactNode;
  /** 实体详情用 40 档 H1 */
  hero?: boolean;
  className?: string;
}) {
  return (
    <header className={`hg-page-head${hero ? " hg-page-head--hero" : ""}${className ? ` ${className}` : ""}`}>
      {breadcrumb && <Breadcrumb items={breadcrumb} />}
      <div className="hg-page-head-main">
        <h1>{title}</h1>
        {meta != null && <div className="hg-page-head-meta">{meta}</div>}
        {subtitle != null && <p className="hg-page-head-sub">{subtitle}</p>}
      </div>
      {actions && <div className="hg-page-head-actions">{actions}</div>}
    </header>
  );
}
