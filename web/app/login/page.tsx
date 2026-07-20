import type { Metadata } from "next";
import { AccountForm } from "@/components/AccountForm";

export const metadata: Metadata = { title: "登录" };
export default function LoginPage() {
  return <div className="auth-page"><section className="auth-intro"><p className="page-kicker">ACCOUNT</p><h1>登录化工社</h1><p>账号只服务于数据贡献、审核追踪与 API 资源管理。查询公开数据不需要登录。</p><ul><li>提交化合物结构与身份信息</li><li>提交或修订结构化反应</li><li>在化合物页面发布反应求助</li></ul></section><section className="auth-panel"><AccountForm /></section></div>;
}
