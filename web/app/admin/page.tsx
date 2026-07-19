import type { Metadata } from "next";
import { AdminReview } from "@/components/AdminReview";

export const metadata: Metadata = { title: "数据审核", robots: { index: false, follow: false } };

export default function AdminPage() {
  return <div className="admin-shell"><h1>数据审核</h1><p className="lead">核对结构、角色、条件和来源；接受后原子写入核心数据。</p><AdminReview /></div>;
}
