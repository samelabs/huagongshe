import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "发布反应" };
export default function SubmitPage() {
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">PUBLISH</p><h1>发布反应</h1><p>你可以直接填写；也可以把网页或文档交给 AI 整理。确认后直接收入你的仓库，并自动建立化合物关联。</p><Link className="text-button" href="/guide">查看 AI 整理与提交指南 →</Link></header><Suspense><SubmissionForm /></Suspense></div>;
}
