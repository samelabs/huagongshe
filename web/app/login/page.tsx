import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";

export const metadata: Metadata = { title: "登录" };
export default function LoginPage() {
  return <div className="auth-page"><section className="auth-intro"><p className="page-kicker">ACCOUNT</p><h1>登录化工社</h1><p>管理个人反应库并关注相关数据。</p><ul><li>发布和维护公开或私有反应</li><li>关注用户、化合物与反应</li><li>使用 API Token 授权 AI</li></ul></section><section className="auth-panel"><AccountForm /></section></div>;
}
