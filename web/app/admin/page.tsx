import type { Metadata } from "next";
import { AdminReview } from "@/components/AdminReview";

export const metadata: Metadata = { title: "数据审核", robots: { index: false, follow: false } };

export default function AdminPage() {
  return <div className="content-page admin-page"><header className="page-title"><p className="page-kicker">REVIEW</p><h1>数据审核</h1><p>先核对结构与身份，再核对角色、条件和来源。审核结论决定是否写入核心数据。</p></header><AdminReview /></div>;
}
