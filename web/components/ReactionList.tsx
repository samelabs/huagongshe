"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet, reactionSvgUrl, type ReactionSummary } from "@/lib/api";
import { EntityId } from "@/components/shared/EntityId";
import t from "@/lib/i18n";

const roles = ["any", "reactant", "product", "reagent", "catalyst", "solvent"] as const;
const roleNames: Record<string, string> = {
  any: t.common.all, reactant: t.chemical.roles.reactant, product: t.chemical.roles.product, reagent: t.chemical.roles.reagent,
  catalyst: t.chemical.roles.catalyst, solvent: t.chemical.roles.solvent,
};

export function ReactionList({ chemicalId, initial, initialTotal }: { chemicalId: number; initial: ReactionSummary[]; initialTotal: number }) {
  const [role, setRole] = useState<string>("any");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ total: number; reactions: ReactionSummary[] }>({ total: initialTotal, reactions: initial });
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    // Skip initial fetch — SSR already provided the authoritative default view.
    if (role === "any" && page === 1) { setData({ total: initialTotal, reactions: initial }); return; }
    let active = true;
    setLoading(true);
    setLoadError(false);
    // 0904 P1收口: 此前 .catch(()=>{}) 静默吞错 — 页码已前进但展示旧页数据,
    // 化学数据场景下是误导性正确性风险。修正(二稿): 失败时保持当前筛选与页码、
    // 数据不换(仍展示上一屏), 只出错误提示行; 不再强制回退 (any,1) 丢用户位置。
    apiGet<{ total: number; reactions: ReactionSummary[] }>(`/chemicals/${chemicalId}/reactions?page=${page}&page_size=8&role=${role}`)
      .then((result) => { if (active) setData({ total: result.total, reactions: result.reactions }); })
      .catch(() => { if (active) setLoadError(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // initial/initialTotal are the SSR snapshot for (any, 1); the reset branch
    // above reads them, so they belong in the dependency set.
  }, [role, page, chemicalId, initial, initialTotal]);

  const pageCount = Math.min(500, Math.max(1, Math.ceil(data.total / 8)));

  return (
    <>
      <div className="role-filter">{roles.map((value) => (
        <button type="button" className={`role-filter-btn${role === value ? " active" : ""}`} key={value} onClick={() => { setRole(value); setPage(1); }}>{roleNames[value]}</button>
      ))}</div>
      {loadError && !loading ? <p className="quiet-empty">{t.common.errRetry}</p> : null}
      {loading ? <p className="quiet-empty">{t.common.loading}</p> : data.reactions.length > 0 ? (
        <div className="reaction-results">{data.reactions.map((reaction) => (
          <article className="reaction-result" key={reaction.id}>
            <div className="reaction-result-main">
              <div className="reaction-result-head">
                <Link href={`/reaction/${reaction.id}`}><EntityId kind="reaction" id={reaction.id} /></Link>
              </div>
              {reaction.reaction_smiles ? (
                <Link className="reaction-preview" href={`/reaction/${reaction.id}`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={reactionSvgUrl(reaction.id, 1100, 220)} width="1100" height="220" alt={t.reaction.equationAlt(reaction.id)} loading="lazy" />
                </Link>
              ) : <div className="reaction-preview unavailable">{t.reaction.equationUnavailable}</div>}
              <div className="reaction-result-foot">
                <p>{[reaction.dataset_name, reaction.doi, reaction.patent].filter(Boolean).join(" · ") || t.reaction.noSource}</p>
                <Link href={`/reaction/${reaction.id}`}>{t.common.view}</Link>
              </div>
            </div>
          </article>
        ))}</div>
      ) : <p className="quiet-empty">{t.chemical.noReactions}</p>}
      {pageCount > 1 && <nav className="pagination" aria-label={t.common.pageNav}>
        {page > 1 && <button type="button" className="pagination-link" onClick={() => setPage(page - 1)}>{t.common.prev}</button>}
        <span>{t.common.pageOf(page, pageCount)}</span>
        {page < pageCount && <button type="button" className="pagination-link" onClick={() => setPage(page + 1)}>{t.common.next}</button>}
      </nav>}
    </>
  );
}
