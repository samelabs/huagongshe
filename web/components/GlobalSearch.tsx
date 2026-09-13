"use client";

import { useRouter } from "next/navigation";
import { useState, useRef } from "react";
import t from "@/lib/i18n";

export function GlobalSearch({ initial = "", compact = false }: {
  initial?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(initial);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    const value = query.trim();
    if (!value) { inputRef.current?.focus(); return; }
    router.push(`/search?q=${encodeURIComponent(value)}`);
  };

  return (
    <div className={`search-wrap${compact ? " search-wrap--compact" : ""}`}>
      <div className="search-row">
        <div className="search-input-box" onClick={() => inputRef.current?.focus()}>
          <svg className="search-input-box__icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.5" y2="16.5" />
          </svg>
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); }}
            placeholder={compact ? t.search.hintNameShort : t.home.searchPlaceholder}
            aria-label={t.search.title}
          />
          {query && (
            <button type="button" className="search-input-box__clear" aria-label={t.search.clearQuery} onClick={() => { setQuery(""); inputRef.current?.focus(); }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
            </button>
          )}
        </div>
        <button type="button" className="search-submit-btn" onClick={submit}>{t.home.searchButton}</button>
      </div>
    </div>
  );
}
