import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { reactionSvgUrl, USER_SUBMITTED_SOURCE, type ReactionLookup, type ReactionSummary } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

/**
 * ReactionResult — 搜索结果行（反应），与化合物结果行同一行语言：
 * 方程式图主视觉（168×92 无框直出）+ HRID 链接与事实行 +
 * 来源行 + 行尾角色标注（静默文本）。行间发丝线分隔，不用卡片框。
 */
export async function ReactionResult({ reaction }: { reaction: ReactionSummary | ReactionLookup }) {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  // 角色标签跟随当前请求字典(原模块级常量依赖静态 zh 字典, 无法按 locale 切换)
  const roleLabels: Record<string, string> = {
    REACTANT: t.submit.roles.reactant, PRODUCT: t.submit.roles.product, REAGENT: t.submit.roles.reagent,
    CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
  };
  const href = withLocale(`/reaction/${reaction.id}`, locale);
  const lookup = "ord_id" in reaction ? reaction : null;
  const sourceLabel = reaction.dataset_name === USER_SUBMITTED_SOURCE ? t.reaction.userSubmitted : reaction.dataset_name;
  const source = [sourceLabel, reaction.doi, reaction.patent, lookup?.ord_id].filter(Boolean).join(" · ");
  const roles = "matched_roles" in reaction
    ? reaction.matched_roles.map((role) => roleLabels[role] || role).join("、")
    : null;
  // 事实摘要: 仅从 reaction_smiles 结构化拆分「N 个反应物 → M 个产物」,
  // 不推断 reaction class / 命名反应, 不发明数据(API 未提供条件时不显示)。
  const facts = reaction.reaction_smiles
    ? (() => {
        const parts = reaction.reaction_smiles.split(">");
        if (parts.length !== 3) return null;
        const count = (side: string) => side.split(".").filter((s) => s.trim()).length;
        const left = count(parts[0]);
        const right = count(parts[2]);
        if (!left || !right) return null;
        return t.search.reactionFacts(left, right);
      })()
    : null;

  return (
    <article className="reaction-result">
      {reaction.reaction_smiles ? (
        <Link className="reaction-result-thumb" href={href} aria-label={t.reaction.equationAlt(reaction.id)}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(reaction.id)} width="1100" height="220" alt={t.reaction.equationAlt(reaction.id)} loading="lazy" />
        </Link>
      ) : (
        <div className="reaction-result-thumb unavailable">{t.reaction.equationUnavailable}</div>
      )}
      <div className="reaction-result-copy">
        <p className="reaction-result-title">
          <Link href={href}><EntityId kind="reaction" id={reaction.id} ariaLabel={t.common.hridLabel(reaction.id)} /></Link>
          {facts && <span>{facts}</span>}
        </p>
        <p className="reaction-result-meta">{source || t.reaction.noSource}</p>
      </div>
      {roles && <span className="reaction-result-roles">{t.reaction.rolePrefix(roles)}</span>}
    </article>
  );
}
