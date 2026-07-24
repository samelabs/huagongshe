"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const CJK_RE = /[\u4e00-\u9fff\u3400-\u4dbf]/;

export function GlobalSearch({ initial = "", compact = false }: {
  initial?: string;
  compact?: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(initial);
  const [notice, setNotice] = useState("");

  return (
    <form className={`global-search${compact ? " compact" : ""}`} onSubmit={(event) => {
      event.preventDefault();
      const value = query.trim();
      if (!value) return;
      if (CJK_RE.test(value)) {
        setNotice("暂不支持中文名称搜索，请使用英文名称、CAS 号、SMILES 或 CID。");
        return;
      }
      setNotice("");
      router.push(`/search?q=${encodeURIComponent(value)}`);
    }}>
      <label className="sr-only" htmlFor={compact ? "site-query-compact" : "site-query"}>查询化学数据</label>
      <input
        id={compact ? "site-query-compact" : "site-query"}
        name="q"
        type="search"
        value={query}
        onChange={(event) => { setQuery(event.target.value); setNotice(""); }}
        placeholder="名称、CAS、SMILES、CID、ORD 记录号或 DOI"
        autoComplete="off"
        enterKeyHint="search"
        maxLength={4000}
      />
      <button type="submit">查询</button>
      {notice && <p className="search-notice">{notice}</p>}
    </form>
  );
}
