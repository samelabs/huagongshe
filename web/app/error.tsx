"use client";

import { useEffect } from "react";

export default function ErrorPage({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => { console.error(error); }, [error]);
  return <main className="content-page error-page">
    <p className="eyebrow">SERVICE TEMPORARILY UNAVAILABLE</p>
    <h1>页面暂时无法加载</h1>
    <p>数据没有丢失，请稍后重试。</p>
    <button className="button primary" type="button" onClick={unstable_retry}>重新加载</button>
  </main>;
}
