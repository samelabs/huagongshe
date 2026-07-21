import type { Metadata } from "next";
import { AccountSettings } from "@/components/AccountSettings";

export const metadata: Metadata = { title: "账号与 Agent", robots: { index: false, follow: false } };
export default function SettingsPage() {
  return <div className="content-page settings-page"><header className="page-title"><p className="page-kicker">SETTINGS</p><h1>账号与 Agent</h1><p>管理公开资料、头像和绑定当前账号的 AI Agent Token。</p></header><AccountSettings /></div>;
}
