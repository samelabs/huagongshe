"use client";

import { useEffect } from "react";
import t from "@/lib/i18n";

export default function WorkbenchError({ error, unstable_retry }: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => { if (process.env.NODE_ENV !== "production") console.error(error); }, [error]);
  return (
    <section className="wb-state wb-state-error">
      <p>{t.error.title}</p>
      <p>{t.error.body}</p>
      <button type="button" onClick={unstable_retry} className="wb-btn wb-btn-ghost">{t.error.retry}</button>
    </section>
  );
}
