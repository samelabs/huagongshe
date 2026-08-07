"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import t from "@/lib/i18n";

const CJK_RE = /[\u4e00-\u9fff\u3400-\u4dbf]/;

export function GlobalSearch({ initial = "", compact = false }: {
  initial?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(initial);
  const [notice, setNotice] = useState("");

  return (
    <div className="global-search-wrap">
      <form className={`global-search${compact ? " compact" : ""}`} onSubmit={(event) => {
        event.preventDefault();
        const value = query.trim();
        if (!value) return;
        if (CJK_RE.test(value)) {
          setNotice(t.search.cjkInline);
          return;
        }
        setNotice("");
        router.push(`/search?q=${encodeURIComponent(value)}`);
      }}>
        <svg className="search-icon" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.5" y2="16.5" /></svg>
        <label className="sr-only" htmlFor={compact ? "site-query-compact" : "site-query"}>{t.search.title}</label>
        <input
          id={compact ? "site-query-compact" : "site-query"}
          name="q"
          type="search"
          value={query}
          onChange={(event) => { setQuery(event.target.value); setNotice(""); }}
          placeholder={t.home.searchPlaceholder}
          autoComplete="off"
          enterKeyHint="search"
          maxLength={4000}
        />
        <button type="submit">{t.home.searchButton}</button>
      </form>
      {notice && <p className="search-notice">{notice}</p>}
    </div>
  );
}
