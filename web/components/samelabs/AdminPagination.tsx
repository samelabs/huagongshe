"use client";

// 三面板统一的紧凑分页: 上一页 | 第 X / Y 页 · 共 N 条 | 下一页
// 文案为后台固定中文, 不进 i18n (Batch 2 决策)。
import { adminTotalPages } from "@/lib/adminPagination";

export type AdminPaginationProps = {
  page: number;
  total: number;
  pageSize: number;
  loading?: boolean;
  onPageChange: (page: number) => void;
};

export function AdminPagination({ page, total, pageSize, loading, onPageChange }: AdminPaginationProps) {
  const totalPages = adminTotalPages(total, pageSize);
  return (
    <div className="admin-pagination">
      <button
        type="button"
        className="admin-pagination-btn"
        disabled={page <= 1 || loading}
        onClick={() => onPageChange(page - 1)}
      >
        上一页
      </button>
      <span className="admin-pagination-meta">
        第 {page} / {totalPages} 页 · 共 {total} 条
      </span>
      <button
        type="button"
        className="admin-pagination-btn"
        disabled={page >= totalPages || loading}
        onClick={() => onPageChange(page + 1)}
      >
        下一页
      </button>
    </div>
  );
}
