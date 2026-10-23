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
 * 结构图主视觉（132×100 无框直出）+ 名称先行（fs-16/600，链接）+
 * 标识行（HCID 徽标 · CAS · 别名 · 分子式）+ 行尾收藏 ghost icon
 * （乐观更新）。行与行之间靠发丝线分隔，不用卡片框。
 * CID 不上行: 它只是数据库标识之一, 详情标识区承载。
 * SMILES 不在行上显示（详情页有 CodeField）。
 */
export async function EntityCard({ chemical, favored = false }: { chemical: Chemical; favored?: boolean }) {
  const t = await getRequestDictionary();
  const locale = await getRequestLocale();
  const { title, secondary } = resolveChemicalName(chemical, t.common.hcidLabel, locale);
  // 标识行: HCID 徽标行首, 其后 CAS 优先, 再随别名与分子式
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
        <h3><Link href={href}>{title}</Link></h3>
        <p className="entity-card-meta">
          <EntityBadge kind="chemical" id={chemical.id} ariaLabel={t.common.hcidLabel(chemical.id)} />
          {identity && <span>{identity}</span>}
        </p>
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
