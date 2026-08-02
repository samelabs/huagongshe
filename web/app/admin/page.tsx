import type { Metadata } from "next";
import { AdminConsole } from "@/components/AdminConsole";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.admin.title, robots: { index: false, follow: false } };

export default function AdminPage() {
  return <div className="content-page admin-page"><header className="page-title"><p className="page-kicker">{t.admin.kicker}</p><h1>{t.admin.title}</h1><p>{t.admin.desc}</p></header><AdminConsole /></div>;
}
