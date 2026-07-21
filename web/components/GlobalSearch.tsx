"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function GlobalSearch({ initial = "", compact = false }: {
  initial?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(initial);

  return (
    <form className={`global-search${compact ? " compact" : ""}`} onSubmit={(event) => {
      event.preventDefault();
      const value = query.trim();
      if (value) router.push(`/search?q=${encodeURIComponent(value)}`);
    }}>
      <label className="sr-only" htmlFor={compact ? "site-query-compact" : "site-query"}>查询化学数据</label>
      <input
        id={compact ? "site-query-compact" : "site-query"}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="名称、CAS、SMILES、CID、ORD 记录号或 DOI"
        autoComplete="off"
      />
      <button type="submit">查询</button>
    </form>
  );
}
