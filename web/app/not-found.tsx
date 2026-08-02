import Link from "next/link";
import t from "@/lib/i18n";
export default function NotFound() { return <div className="empty-state"><p>{t.error.notFoundTitle}</p><Link className="text-link" href="/">{t.error.notFoundAction}</Link></div>; }
