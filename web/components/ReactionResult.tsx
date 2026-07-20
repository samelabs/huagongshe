import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import { reactionSvgUrl, type ReactionLookup, type ReactionSummary } from "@/lib/api";

const roleLabels: Record<string, string> = {
  REACTANT: "反应物", PRODUCT: "生成物", REAGENT: "试剂",
  CATALYST: "催化剂", SOLVENT: "溶剂",
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
      <Link className="reaction-preview" href={`/reaction/${reaction.id}`}>
        {/* The endpoint renders the stored RDKit reaction, never user HTML. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={reactionSvgUrl(reaction.id, 1100, 220)} width="1100" height="220" alt={`反应 ${reaction.id} 方程式`} loading="lazy" />
      </Link>
      <div className="reaction-result-foot">
        <p>{source || "结构数据已入库，来源信息待补全"}</p>
        <Link href={`/reaction/${reaction.id}`}>查看条件与参与物</Link>
      </div>
    </article>
  );
}
