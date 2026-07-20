import type { Metadata } from "next";
import { Suspense } from "react";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "提交数据" };
export default function SubmitPage() {
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">CONTRIBUTE</p><h1>贡献化学数据</h1><p>结构化提交，自动校验，人工审核后进入 chemicals 或 reactions；每次提交都有可追踪结果。</p></header><Suspense><SubmissionForm /></Suspense></div>;
}
