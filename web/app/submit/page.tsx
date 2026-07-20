import type { Metadata } from "next";
import { Suspense } from "react";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "提交数据" };
export default function SubmitPage() {
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">CONTRIBUTE</p><h1>贡献化学数据</h1><p>提交内容通过校验和人工审核后公开，审核结果可追踪。</p></header><Suspense><SubmissionForm /></Suspense></div>;
}
