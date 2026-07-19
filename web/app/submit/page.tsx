import type { Metadata } from "next";
import { Suspense } from "react";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "提交数据" };
export default function SubmitPage() {
  return <div className="auth-card"><h1>提交数据</h1><p className="lead">提交内容经格式校验和人工审核后进入化工社数据。</p><Suspense><SubmissionForm /></Suspense></div>;
}
