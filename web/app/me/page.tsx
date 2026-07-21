import type { Metadata } from "next";
import { UserDashboard } from "@/components/UserDashboard";

export const metadata: Metadata = { title: "我的反应仓库", robots: { index: false, follow: false } };
export default function MePage() {
  return <div className="content-page dashboard-page"><UserDashboard /></div>;
}
