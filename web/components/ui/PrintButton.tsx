"use client";

/**
 * PrintButton — 打印页工具栏的打印按钮。调起系统打印对话框；
 * 打印对话框里可选「存储为 PDF」，文案同时写明两种用途。
 */
export function PrintButton({ label }: { label: string }) {
  return (
    <button type="button" className="pr-btn" onClick={() => window.print()}>
      {label}
    </button>
  );
}
