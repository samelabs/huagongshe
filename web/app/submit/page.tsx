import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "发布反应" };
export default function SubmitPage() {
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">PUBLISH</p><h1>发布反应</h1><p>填写结构化反应，或先由 AI 从文献和实验记录中整理。提交后自动关联相关化合物。</p><Link className="text-button" href="/guide">查看 AI 提交指南 →</Link></header><Suspense><SubmissionForm /></Suspense></div>;
}
