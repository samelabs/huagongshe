import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { reactionSvgUrl, type ReactionLookup, type ReactionSummary } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

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
  const source = [reaction.dataset_name, reaction.doi, reaction.patent].filter(Boolean).join(" · ");
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
      <div className="reaction-result-head">
        <div>
          <Link href={href}><EntityId kind="reaction" id={reaction.id} ariaLabel={t.common.hridLabel(reaction.id)} /></Link>
          {facts && <p className="reaction-result-summary">{facts}</p>}
          {reaction.dataset_name && <p className="reaction-source-name">{reaction.dataset_name}</p>}
        </div>
        <div className="reaction-badges">
          {roles && <span>{t.reaction.rolePrefix(roles)}</span>}
          {lookup?.ord_id && <span>{lookup.ord_id}</span>}
        </div>
      </div>
      {reaction.reaction_smiles ? (
        <Link className="reaction-preview" href={href}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(reaction.id, 1100, 220)} width="1100" height="220" alt={t.reaction.equationAlt(reaction.id)} loading="lazy" />
        </Link>
      ) : <div className="reaction-preview unavailable">{t.reaction.equationUnavailable}</div>}
      <div className="reaction-result-foot">
        <p>{source || t.reaction.noSource}</p>
        <Link href={href}>{t.common.view}</Link>
      </div>
    </article>
  );
}
