import Link from "next/link";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

export default async function NotFound() {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  return <div className="app-container"><div className="empty-state"><p>{t.error.notFoundTitle}</p><Link className="text-link" href={withLocale("/", locale)}>{t.error.notFoundAction}</Link></div></div>;
}
