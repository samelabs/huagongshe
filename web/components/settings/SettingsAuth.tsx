"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function LoginRequired({ text }: { text: string }) {
  const pathname = usePathname();
  return <div className="auth-required"><div><strong>请先登录</strong><span>{text}</span></div><Link href={`/login?next=${encodeURIComponent(pathname)}`}>登录</Link></div>;
}
