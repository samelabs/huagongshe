"use client";

import { useState } from "react";
import t from "@/lib/i18n";

export function ShareButton({ title }: { title?: string } = {}) {
  const [copied, setCopied] = useState(false);
  async function share() {
    const url = typeof window !== "undefined" ? window.location.href : "https://huagongshe.com/guide";
    const shareTitle = title ?? t.guide.title;
    if (navigator.share) {
      try {
        await navigator.share({ title: shareTitle, url });
        return;
      } catch { /* user cancelled, fall through to copy */ }
    }
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { /* clipboard blocked */ }
  }
  return <button type="button" className="button secondary small" onClick={share}>{copied ? t.guide.shareCopied : t.guide.share}</button>;
}
