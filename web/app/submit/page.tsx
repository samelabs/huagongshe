import type { Metadata } from "next";
import { Suspense } from "react";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "提交数据" };
export default function SubmitPage() {
  return <div className="submit-shell"><h1>提交数据</h1><p className="lead">结构校验 → 人工审核 → 写入核心数据；审核结果可追踪。</p><Suspense><SubmissionForm /></Suspense></div>;
}
