import Link from "next/link";
import { Molecule } from "@/components/chemical/Molecule";
import { FollowButton } from "@/components/shared/FollowButton";
import { EntityBadge } from "@/components/ui/EntityBadge";
import type { Chemical } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

/**
 * EntityCard（chemical）— 搜索结果行（DESIGN_SYSTEM 3.13/6.2）。
 * 无卡片框：结构图按原生比例直出（112×84 位）+ HCID 徽标 sm + 名称
 * （fs-16/600，链接）+ 元信息（别名 · CAS · 分子式）+ 右侧收藏 ghost
 * icon（乐观更新) —— 外围卡片框会挤压 1:1 结构图的可读性。
 * CID 不上行: 它只是数据库标识之一, 详情标识区承载。
 * SMILES 不在行上显示（详情页有 CodeField）。
 */
export async function EntityCard({ chemical, favored = false }: { chemical: Chemical; favored?: boolean }) {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  const { title, secondary } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  // 标签区: CAS 优先, 其后随
  const identity = [
    chemical.cas_numbers[0] ? `CAS ${chemical.cas_numbers[0]}` : null,
    secondary,
    chemical.molecular_formula,
  ].filter(Boolean).join(" · ");
  const href = withLocale(`/chemical/${chemical.id}`, locale);

  return (
    <article className="entity-card">
      <Link className="entity-card-thumb" href={href} aria-label={`${t.common.view} ${title}`}>
        <Molecule chemicalId={chemical.id} smiles={chemical.smiles} size="sm" label={title} alt={t.chemical.structureAlt(title)} noStructureText={t.chemical.noStructure} />
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
