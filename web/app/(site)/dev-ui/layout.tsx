import { notFound } from "next/navigation";

/**
 * dev-ui 预览页的生产闸（DESIGN_SYSTEM 1.6：非生产环境可访问）。
 * noindex 只是搜索指示，不拦访问；生产构建在此直接 404 ——
 * NODE_ENV 在构建期内联，生产包里该分支恒为 notFound。
 */
export default function DevUiLayout({ children }: { children: React.ReactNode }) {
  if (process.env.NODE_ENV === "production") notFound();
  return <>{children}</>;
}
