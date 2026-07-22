import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";

export const metadata: Metadata = { title: "登录" };
export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string | string[] }> }) {
  const query = await searchParams;
  const nextPath = safeNextPath(typeof query.next === "string" ? query.next : null);
  return <div className="auth-page"><section className="auth-intro"><p className="page-kicker">个人中心</p><h1>登录化工社</h1><p>保存个人反应、收藏化学数据，并连接你的 AI 助手。</p><ul><li>管理公开或仅自己可见的反应记录</li><li>收藏需要继续查阅的化合物与反应</li><li>授权 AI 查询、校验并新建反应记录</li></ul></section><section className="auth-panel"><AccountForm nextPath={nextPath} /></section></div>;
}

function safeNextPath(value: string | null) {
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/me";
}
