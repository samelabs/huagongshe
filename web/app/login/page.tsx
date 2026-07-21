import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";

export const metadata: Metadata = { title: "登录" };
export default function LoginPage() {
  return <div className="auth-page"><section className="auth-intro"><p className="page-kicker">ACCOUNT</p><h1>登录化工社</h1><p>建立自己的反应仓库，并用关注连接用户、化合物和反应。</p><ul><li>发布和维护公开或私有反应</li><li>关注用户、化合物与反应</li><li>创建绑定账号的 AI Agent Token</li></ul></section><section className="auth-panel"><AccountForm /></section></div>;
}
