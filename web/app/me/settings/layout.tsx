import type { Metadata } from "next";
import { SettingsNav } from "@/components/settings/SettingsNav";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: { default: t.settings.title, template: `%s · ${t.settings.title}` }, robots: { index: false, follow: false } };

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return <div className="content-page settings-page">
    <header className="page-title settings-title"><p className="page-kicker">{t.settings.titleKicker}</p><h1>{t.settings.title}</h1><p>{t.settings.subtitle}</p></header>
    <div className="settings-layout"><SettingsNav /><div className="settings-content">{children}</div></div>
  </div>;
}
