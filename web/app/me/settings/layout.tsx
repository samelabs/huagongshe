import type { Metadata } from "next";
import { SettingsNav } from "@/components/settings/SettingsNav";

export const metadata: Metadata = { title: { default: "账户设置", template: "%s · 账户设置" }, robots: { index: false, follow: false } };

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <div className="content-page settings-page">
    <header className="page-title settings-title"><p className="page-kicker">SETTINGS</p><h1>账户设置</h1><p>账户资料、安全信息和 API 授权分别管理。</p></header>
    <div className="settings-layout"><SettingsNav /><div className="settings-content">{children}</div></div>
  </div>;
}
