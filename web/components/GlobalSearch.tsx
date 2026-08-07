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
    <div className="search-wrap">
      <form
        className={`search-bar${compact ? " search-bar--compact" : ""}`}
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          const value = query.trim();
          if (!value) return;
          if (CJK_RE.test(value)) {
            setNotice(t.search.cjkInline);
            return;
          }
          setNotice("");
          router.push(`/search?q=${encodeURIComponent(value)}`);
        }}
      >
        <span className="search-bar__icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.5" y2="16.5" />
          </svg>
        </span>
        <label className="sr-only" htmlFor={compact ? "q-compact" : "q"}>
          {t.search.title}
        </label>
        <input
          id={compact ? "q-compact" : "q"}
          name="q"
          type="text"
          inputMode="search"
          enterKeyHint="search"
          value={query}
          onChange={(event) => { setQuery(event.target.value); setNotice(""); }}
          placeholder={t.home.searchPlaceholder}
          autoComplete="off"
          spellCheck={false}
          maxLength={4000}
          className="search-bar__input"
        />
        <button type="submit" className="search-bar__btn">
          {t.home.searchButton}
        </button>
      </form>
      {notice && <p className="search-notice">{notice}</p>}
    </div>
  );
}
