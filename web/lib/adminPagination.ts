// Admin 列表分页纯函数 (Batch 2) — users/reactions/skills 三面板共用。
// 后端只认 limit+offset (Batch 1 契约不变); 1-based page 在前端换算。
export const PAGE_SIZE = 50;

// URL page 解析: 非法值(0/负数/非整数/非数字/科学计数/带空格)一律回 1
export function parseAdminPage(raw: string | null): number {
  if (raw === null || !/^\d+$/.test(raw)) return 1;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1 ? n : 1;
}

export function adminOffset(page: number, pageSize: number = PAGE_SIZE): number {
  return (page - 1) * pageSize;
}

export function adminTotalPages(total: number, pageSize: number = PAGE_SIZE): number {
  return Math.max(1, Math.ceil(total / pageSize));
}
