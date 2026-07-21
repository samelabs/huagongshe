import type { Metadata } from "next";
import { Suspense } from "react";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "发布反应" };
export default function SubmitPage() {
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">PUBLISH</p><h1>发布反应</h1><p>结构校验通过后直接收入你的反应仓库，并自动建立化合物关联。</p></header><Suspense><SubmissionForm /></Suspense></div>;
}
