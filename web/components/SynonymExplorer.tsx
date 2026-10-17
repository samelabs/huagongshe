"use client";

import { useState } from "react";
import { apiGet } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { TextLink } from "@/components/ui/TextLink";

/**
 * SynonymExplorer (Design System v2, Issue #4 重组)。
 *
 * 页面 IA 归 Names & Identifiers; 本组件只负责 preview 之外的展开与 load-more。
 * 关键约束: preview 已有前 N 条, 这里**不得重复渲染** —— 只渲染 items.slice(shown) 起。
 *
 * 分页终止不再用「去重后条数 vs 原始 total」
 * （同义词含重复时去重数永远追不上 total → 同一页被无限重拉）。改按**已请求的
 * 原始 offset** 判断：loaded 记录累计拉取的原始条数，页码 = floor(loaded/100)+1，
 * loaded ≥ total 或接口返回空页即停；另有 50 次请求的硬上限保护。
 */
const PAGE_SIZE = 100;
const MAX_REQUESTS = 50;

export function SynonymExplorer({ chemicalId, initial, total, shown }: {
  chemicalId: number;
  initial: string[];
  total: number;
  shown: number;
}) {
  const t = useDictionary();
  const [items, setItems] = useState(() => Array.from(new Set(initial)));
  const [loaded, setLoaded] = useState(initial.length); // 已覆盖的原始条数（不去重）
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [exhausted, setExhausted] = useState(initial.length >= total);
  const [requests, setRequests] = useState(0);

  async function loadMore() {
    if (busy || exhausted || requests >= MAX_REQUESTS) return;
    setBusy(true);
    setFailed(false);
    const page = Math.floor(loaded / PAGE_SIZE) + 1;
    try {
      const data = await apiGet<{ synonyms: string[] }>(`/chemicals/${chemicalId}/synonyms?page=${page}&page_size=${PAGE_SIZE}`);
      setItems((current) => Array.from(new Set([...current, ...data.synonyms])));
      const nextLoaded = loaded + (data.synonyms?.length ?? 0);
      setLoaded(nextLoaded);
      // 终止：offset 已覆盖 total，或接口返回空页（数据被清理等）
      if (nextLoaded >= total || !data.synonyms?.length) setExhausted(true);
    } catch {
      setFailed(true);
    } finally {
      setRequests((n) => n + 1);
      setBusy(false);
    }
  }

  if (!total) return null;
  const rest = items.slice(shown); // preview 已展示的不重复
  const done = exhausted || requests >= MAX_REQUESTS;
  return (
    <>
      {rest.length > 0 && (
        <div className="alias-list synonym-full">
          {rest.map((item) => <span key={item}>{item}</span>)}
        </div>
      )}
      {!done && (
        /* 与上下游品名的展开按钮同形态：按钮移出胶囊容器独立成行，
           不再因 flex 拉伸撑高同排胶囊 */
        <div className="casext-toggle-row">
          <TextLink className="synonym-more" onClick={loadMore} disabled={busy}>{busy ? t.common.loading : t.chemical.synonyms.loadMore(items.length)}</TextLink>
        </div>
      )}
      {failed && <p className="inline-error">{t.chemical.synonyms.error}</p>}
    </>
  );
}
