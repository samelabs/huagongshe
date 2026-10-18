import type { ReactNode } from "react";
import { Breadcrumb, type BreadcrumbItem } from "./Breadcrumb";

/**
 * PageHead — 页头（版式基准）：面包屑 + H1 + 副标题 + 元信息 + 操作区。
 *
 * H1 两档：default 28（列表/文章页）、hero 28/22（实体详情页，手机 22）；
 * 字重恒 --fw-semibold，行高 --lh-heading，字距 0。
 * 主区内渲染序固定为 副标题（纯文本，如实体外文名）→ 块级元信息
 * （如实体身份行）→ 互动行（hero 变体）；默认页头的操作区仍在页头右端。
 */
export function PageHead({
  breadcrumb,
  title,
  subtitle,
  meta,
  actions,
  aside,
  hero = false,
  className,
}: {
  breadcrumb?: BreadcrumbItem[];
  title: ReactNode;
  subtitle?: ReactNode;
  /** 标题行的块级元信息（如作者署名），与纯文本副标题并列 */
  meta?: ReactNode;
  actions?: ReactNode;
  /** 页头右侧的视觉位（如实体详情的结构件卡片），与正文左缘同框右置 */
  aside?: ReactNode;
  /** 实体详情用 40 档 H1 */
  hero?: boolean;
  className?: string;
}) {
  return (
    <header className={`hg-page-head${hero ? " hg-page-head--hero" : ""}${className ? ` ${className}` : ""}`}>
      {breadcrumb && <Breadcrumb items={breadcrumb} />}
      <div className="hg-page-head-main">
        <h1>{title}</h1>
        {subtitle != null && <p className="hg-page-head-sub">{subtitle}</p>}
        {meta != null && <div className="hg-page-head-meta">{meta}</div>}
        {/* hero 页头：互动行是标题块的末行（紧贴元信息，不跨列悬空） */}
        {hero && actions && <div className="hg-page-head-actions">{actions}</div>}
      </div>
      {!hero && actions && <div className="hg-page-head-actions">{actions}</div>}
      {aside && <div className="hg-page-head-aside">{aside}</div>}
    </header>
  );
}
