import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";

export const metadata: Metadata = { title: "登录" };
export default function LoginPage() {
  return <div className="auth-card"><h1>登录化工社</h1><p className="lead">登录后可提交和维护化合物与反应数据。</p><AccountForm /></div>;
}
