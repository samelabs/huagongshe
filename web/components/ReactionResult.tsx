import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import { reactionSvgUrl, type ReactionLookup, type ReactionSummary } from "@/lib/api";
import t from "@/lib/i18n";

const roleLabels: Record<string, string> = {
  REACTANT: t.submit.roles.reactant, PRODUCT: t.submit.roles.product, REAGENT: t.submit.roles.reagent,
  CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
};

export function ReactionResult({ reaction }: { reaction: ReactionSummary | ReactionLookup }) {
  const lookup = "ord_id" in reaction ? reaction : null;
  const source = [reaction.dataset_name, reaction.doi, reaction.patent].filter(Boolean).join(" · ");
  const roles = "matched_roles" in reaction
    ? reaction.matched_roles.map((role) => roleLabels[role] || role).join("、")
    : null;

  return (
    <article className="reaction-result">
      <div className="reaction-result-head">
        <div>
          <Link href={`/reaction/${reaction.id}`}><EntityId kind="reaction" id={reaction.id} /></Link>
          {reaction.dataset_name && <p className="reaction-source-name">{reaction.dataset_name}</p>}
        </div>
        <div className="reaction-badges">
          {roles && <span>作为{roles}</span>}
          {lookup?.ord_id && <span>{lookup.ord_id}</span>}
        </div>
      </div>
      {reaction.reaction_smiles ? (
        <Link className="reaction-preview" href={`/reaction/${reaction.id}`}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={reactionSvgUrl(reaction.id, 1100, 220)} width="1100" height="220" alt={`HRID ${reaction.id} 反应方程式`} loading="lazy" />
        </Link>
      ) : <div className="reaction-preview unavailable">{t.reaction.equationUnavailable}</div>}
      <div className="reaction-result-foot">
        <p>{source || t.reaction.noSource}</p>
        <Link href={`/reaction/${reaction.id}`}>{t.common.view}</Link>
      </div>
    </article>
  );
}
