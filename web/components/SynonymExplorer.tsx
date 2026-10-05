"use client";

import { useState } from "react";
import { apiGet } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";

/**
 * SynonymExplorer (Design System v2, Issue #4 重组)。
 *
 * 页面 IA 归 Names & Identifiers; 本组件只负责 preview 之外的展开与 load-more。
 * 关键约束: preview 已有前 N 条, 这里**不得重复渲染** —— 只渲染 items.slice(shown) 起。
 * 数据获取逻辑不变(page_size=100 分页, 客户端去重)。
 */
export function SynonymExplorer({ chemicalId, initial, total, shown }: {
  chemicalId: number;
  initial: string[];
  total: number;
  shown: number;
}) {
  const t = useDictionary();
  const [items, setItems] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function loadMore() {
    setBusy(true);
    setFailed(false);
    const page = Math.floor(items.length / 100) + 1;
    try {
      const data = await apiGet<{ synonyms: string[] }>(`/chemicals/${chemicalId}/synonyms?page=${page}&page_size=100`);
      setItems((current) => Array.from(new Set([...current, ...data.synonyms])));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (!total) return null;
  const rest = items.slice(shown); // preview 已展示的不重复
  return (
    <>
      {rest.map((item) => <span key={item}>{item}</span>)}
      {items.length < total && (
        <button className="text-button synonym-more" type="button" onClick={loadMore} disabled={busy}>
          {busy ? t.common.loading : t.chemical.synonyms.loadMore(items.length)}
        </button>
      )}
      {failed && <p className="inline-error">{t.chemical.synonyms.error}</p>}
    </>
  );
}
