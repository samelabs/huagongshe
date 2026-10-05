"use client";

import { useState } from "react";
import { useDictionary } from "@/components/shared/I18nContext";

export function AiSubmissionPrompt() {
  const t = useDictionary();
  const prompt = t.guide.aiPrompt;
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
