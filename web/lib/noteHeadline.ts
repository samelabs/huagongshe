/** 笔记标题行：首个非空行（≤60 字）— 工作台面板与公开主页共用。
 *  放在 lib（非 "use client" 模块）以便服务端页面直接调用。 */
export function noteHeadline(content: string): string {
  const first = content.split("\n").map((l) => l.trim()).find((l) => l.length > 0) ?? "";
  return first.length > 60 ? `${first.slice(0, 60)}…` : first;
}
