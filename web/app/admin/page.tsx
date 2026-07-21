import type { Metadata } from "next";
import { AdminConsole } from "@/components/AdminConsole";

export const metadata: Metadata = { title: "平台管理", robots: { index: false, follow: false } };

export default function AdminPage() {
  return <div className="content-page admin-page"><header className="page-title"><p className="page-kicker">ADMIN</p><h1>平台管理</h1><p>管理用户账号和用户内容可见度，不审核化学结论。</p></header><AdminConsole /></div>;
}
