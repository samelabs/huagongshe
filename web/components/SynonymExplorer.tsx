"use client";

import { useState } from "react";

export function SynonymExplorer({ chemicalId, initial, total }: {
  chemicalId: number;
  initial: string[];
  total: number;
}) {
  const [items, setItems] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function loadMore() {
    setBusy(true);
    setFailed(false);
    const page = Math.floor(items.length / 100) + 1;
    const response = await fetch(`/api/chemicals/${chemicalId}/synonyms?page=${page}&page_size=100`);
    if (!response.ok) {
      setFailed(true);
      setBusy(false);
      return;
    }
    const data = await response.json() as { synonyms: string[] };
    setItems((current) => Array.from(new Set([...current, ...data.synonyms])));
    setBusy(false);
  }

  if (!total) return null;
  return (
    <section className="aliases-section" aria-labelledby="aliases-title">
      <div className="section-heading compact-heading">
        <div><p>ALIASES</p><h2 id="aliases-title">名称与别名</h2></div>
        <span>共 {new Intl.NumberFormat("zh-CN").format(total)} 条</span>
      </div>
      <div className="alias-list">{items.map((item) => <span key={item}>{item}</span>)}</div>
      {items.length < total && (
        <button className="text-button" type="button" onClick={loadMore} disabled={busy}>
          {busy ? "正在读取…" : `继续读取（已显示 ${items.length} 条）`}
        </button>
      )}
      {failed && <p className="inline-error">别名暂时无法继续读取。</p>}
    </section>
  );
}
