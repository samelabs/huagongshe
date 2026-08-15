"use client";

import { useState } from "react";
import t from "@/lib/i18n";

const prompt = t.guide.aiPrompt;

export function AiSubmissionPrompt() {
  const [copied, setCopied] = useState(false);
  async function copy() {
    await navigator.clipboard.writeText(prompt);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }
  return <div className="prompt-box">
    <pre>{prompt}</pre>
        <button type="button" className="button secondary small" onClick={copy}>{copied ? t.guide.copyPrompt(true) : t.guide.copyPrompt(false)}</button>
  </div>;
}
