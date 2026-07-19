"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function SearchBox({ initial = "", initialMode = "exact", autoFocus = false }: { initial?: string; initialMode?: string; autoFocus?: boolean }) {
  const router = useRouter();
  const [query, setQuery] = useState(initial);
  const [mode, setMode] = useState(initialMode);
  return (
    <form className="search-form" onSubmit={(event) => {
      event.preventDefault();
      const value = query.trim();
      if (value) router.push(`/search?q=${encodeURIComponent(value)}&mode=${mode}`);
    }}>
      <input
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="名称、CAS、SMILES 或外部编号"
        aria-label="搜索化合物"
        autoFocus={autoFocus}
      />
      <select value={mode} onChange={(event) => setMode(event.target.value)} aria-label="检索方式">
        <option value="exact">自动识别</option>
        <option value="substructure">子结构</option>
        <option value="similarity">相似结构</option>
      </select>
      <button type="submit">查询</button>
    </form>
  );
}
