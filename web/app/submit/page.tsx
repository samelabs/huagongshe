import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { SubmissionForm } from "@/components/SubmissionForm";

export const metadata: Metadata = { title: "反应记录" };
export default async function SubmitPage({ searchParams }: { searchParams: Promise<{ reaction?: string | string[] }> }) {
  const query = await searchParams;
  const editing = typeof query.reaction === "string" && /^\d+$/.test(query.reaction);
  return <div className="content-page submission-page"><header className="page-title"><p className="page-kicker">MY REACTION</p><h1>{editing ? "编辑反应记录" : "新建反应记录"}</h1><p>{editing ? "修改这条反应的结构、条件、来源或可见范围。" : "保存结构化反应记录，并自动关联相关化合物。新记录默认仅自己可见。"}</p><Link className="text-button" href="/guide">了解如何使用 AI 整理 →</Link></header><Suspense><SubmissionForm /></Suspense></div>;
}
