"use client";

import { useEffect } from "react";
import t from "@/lib/i18n";

export default function ErrorPage({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => { if (process.env.NODE_ENV !== "production") console.error(error); }, [error]);
  return <div className="app-container">
    <main className="content-page error-page">
      <p className="eyebrow">SERVICE TEMPORARILY UNAVAILABLE</p>
      <h1>{t.error.title}</h1>
      <p>{t.error.body}</p>
      <button className="button primary" type="button" onClick={unstable_retry}>{t.error.retry}</button>
    </main>
  </div>;
}
