"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet, reactionSvgUrl, type ReactionSummary } from "@/lib/api";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Segmented } from "@/components/ui/Segmented";
import { Tag } from "@/components/ui/Tag";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

const roles = ["any", "reactant", "product", "reagent", "catalyst", "solvent"] as const;
type Role = (typeof roles)[number];

export function ReactionList({ chemicalId, initial, initialTotal }: { chemicalId: number; initial: ReactionSummary[]; initialTotal: number }) {
  const t = useDictionary();
  const locale = useLocale();
  // 角色标签跟随当前请求字典(原模块级常量依赖静态 zh 字典)
  const roleNames: Record<string, string> = {
    any: t.common.all, reactant: t.chemical.roles.reactant, product: t.chemical.roles.product, reagent: t.chemical.roles.reagent,
    catalyst: t.chemical.roles.catalyst, solvent: t.chemical.roles.solvent,
  };
  const [role, setRole] = useState<Role>("any");
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
      <Segmented<Role>
        className="reaction-role-seg"
        ariaLabel={t.chemical.relatedReactions}
        options={roles.map((value) => ({ value, label: roleNames[value] }))}
        value={role}
        onChange={(value) => { setRole(value); setPage(1); }}
      />
      {loadError && !loading ? <p className="quiet-empty">{t.common.errRetry}</p> : null}
      {loading ? <p className="quiet-empty">{t.common.loading}</p> : data.reactions.length > 0 ? (
        <div className="reaction-results">{data.reactions.map((reaction) => (
          <article className="reaction-result" key={reaction.id}>
            <div className="reaction-result-main">
              <div className="reaction-result-head">
                <EntityBadge
                  kind="reaction"
                  id={reaction.id}
                  size="md"
                  href={withLocale(`/reaction/${reaction.id}`, locale)}
                  ariaLabel={t.common.hridLabel(reaction.id)}
                />
                {reaction.matched_roles.length > 0 && (
                  <span className="reaction-role-tags">
                    {reaction.matched_roles.map((r) => <Tag key={r}>{roleNames[r.toLowerCase()] ?? r}</Tag>)}
                  </span>
                )}
              </div>
              {reaction.reaction_smiles ? (
                <Link className="reaction-preview" href={withLocale(`/reaction/${reaction.id}`, locale)}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={reactionSvgUrl(reaction.id, 1100, 220)} width="1100" height="220" alt={t.reaction.equationAlt(reaction.id)} loading="lazy" />
                </Link>
              ) : <div className="reaction-preview unavailable">{t.reaction.equationUnavailable}</div>}
              <div className="reaction-result-foot">
                <p>{[reaction.dataset_name, reaction.doi, reaction.patent].filter(Boolean).join(" · ") || t.reaction.noSource}</p>
                <Link href={withLocale(`/reaction/${reaction.id}`, locale)}>{t.common.view}</Link>
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
