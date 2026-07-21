"use client";

import Link from "next/link";

export function LoginRequired({ text }: { text: string }) {
  return <div className="auth-required"><div><strong>请先登录</strong><span>{text}</span></div><Link href="/login">登录</Link></div>;
}
