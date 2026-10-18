/**
 * 工作台路由判定 —— 服务端外壳取数与客户端顶栏动作显隐共用的纯函数，
 * 不依赖 next/headers，客户端组件可直接引用。
 *
 * 工作台路由族：/aichem 及其子页、/submit、/me。输入为去掉 locale
 * 前缀后的站内路径。
 */
export function isWorkbenchRoute(rest: string): boolean {
  if (rest === "/aichem" || rest.startsWith("/aichem/")) return true;
  if (rest.startsWith("/submit")) return true;
  if (rest.startsWith("/me")) return true;
  return false;
}
