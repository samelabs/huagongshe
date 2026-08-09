import type { Metadata } from "next";
import t from "@/lib/i18n";

export const metadata: Metadata = {
  title: { default: t.admin.title, template: `%s · ${t.admin.title}` },
  robots: { index: false, follow: false },
};

export default function SamelabsLayout({ children }: { children: React.ReactNode }) {
  return <div className="content-page samelabs-page">{children}</div>;
}
