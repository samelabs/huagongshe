import Link from "next/link";
import { Molecule } from "@/components/Molecule";
import { FollowButton } from "@/components/shared/FollowButton";
import { EntityBadge } from "@/components/ui/EntityBadge";
import type { Chemical } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

/**
 * EntityCard（chemical）— 搜索结果卡片（DESIGN_SYSTEM §6/§9.3，Step 10）。
 * 结构缩略图 112×84 + HCID 徽标 sm + 名称（fs-16/600，链接）+ 元信息
 * （别名 · CAS · CID · 分子式）+ 右侧收藏 ghost icon（乐观更新，IX-6）。
 * SMILES 不在卡片显示（详情页有 CodeField）。
 */
export async function EntityCard({ chemical, favored = false }: { chemical: Chemical; favored?: boolean }) {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  const { title, secondary } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  const identity = [
    secondary,
    chemical.cas_numbers[0] ? `CAS ${chemical.cas_numbers[0]}` : null,
    chemical.pubchem_cid ? `CID ${chemical.pubchem_cid}` : null,
    chemical.molecular_formula,
  ].filter(Boolean).join(" · ");
  const href = withLocale(`/chemical/${chemical.id}`, locale);

  return (
    <article className="entity-card">
      <Link className="entity-card-thumb" href={href} aria-label={`${t.common.view} ${title}`}>
        <Molecule chemicalId={chemical.id} width={112} height={84} label={title} alt={t.chemical.structureAlt(title)} noStructureText={t.reaction.noStructure} />
      </Link>
      <div className="entity-card-copy">
        <EntityBadge kind="chemical" id={chemical.id} ariaLabel={t.common.hcidLabel(chemical.id)} />
        <h3><Link href={href}>{title}</Link></h3>
        {identity && <p className="entity-card-meta">{identity}</p>}
      </div>
      <FollowButton
        endpoint={`/chemicals/${chemical.id}/follow`}
        initial={favored}
        label="favor"
        variant="ghost"
        iconOnly
        showCount={false}
      />
    </article>
  );
}
