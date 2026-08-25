import t from "@/lib/i18n";

/**
 * CB 中文扩展条目 + 供应商（详情页 ChemicalKnowledge 之上前置渲染）。
 * 无区块总标题；分区用数据原生分区名，样式复用详情页现有分区体系。
 * 数据即内容：CB 原生中文键值/散文作为数据渲染，不进语言包；
 * 界面铬文案全部走 t()。
 */

export type CasEntry = {
  basic?: [string, string][];
  aliases?: { cn?: string[]; en?: string[] };
  props?: [string, string][];
  safety?: [string, string][];
  prose?: { title: string; text: string }[];
  updown?: { up?: string[]; down?: string[] };
  reagents?: { vendor: string; text: string }[];
};

export type CasSupplier = {
  ref: string;
  name: string;
  phone: string | null;
  email: string | null;
  website: string | null;
  purity: string | null;
  pack_price: string | null;
  remark: string | null;
};

export type CasExternalsPayload = {
  chemical_id: number;
  state: string;
  entry: CasEntry | null;
  suppliers: CasSupplier[];
};

const PROSE_GROUP_TITLES: Record<string, string> = {
  应用领域: t.chemical.casext.uses,
  制备方法: t.chemical.casext.preparation,
  常见问题列表: t.chemical.casext.faq,
  毒性防护: t.chemical.casext.toxicity,
  包装储运: t.chemical.casext.packaging,
};

export function CasExternals({ payload }: { payload: CasExternalsPayload | null }) {
  const { entry, suppliers } = payload ?? { entry: null, suppliers: [] };
  if (!entry && (!suppliers || suppliers.length === 0)) return null; // 无数据整块不渲染

  const aliases = entry?.aliases;
  const hasAliasBlock = Boolean(aliases && ((aliases.cn && aliases.cn.length) || (aliases.en && aliases.en.length)));

  return (
    <>
      {entry?.basic && entry.basic.length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>BASIC</p><h2>{t.chemical.casext.basic}</h2></div></div>
          <dl className="identity-table">
            {entry.basic.map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {hasAliasBlock && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>ALIASES</p><h2>{t.chemical.casext.aliases}</h2></div></div>
          <div className="casext-tags">
            {aliases?.cn?.map((name) => <span key={`cn-${name}`} className="casext-tag">{name}</span>)}
            {aliases?.en?.map((name) => <span key={`en-${name}`} className="casext-tag en">{name}</span>)}
          </div>
        </section>
      )}

      {entry?.props && entry.props.length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>PROPERTIES</p><h2>{t.chemical.casext.props}</h2></div></div>
          <dl className="identity-table">
            {entry.props.map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {entry?.safety && entry.safety.length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>SAFETY</p><h2>{t.chemical.casext.safety}</h2></div></div>
          <dl className="identity-table">
            {entry.safety.map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {entry?.prose && entry.prose.length > 0 && <CasProseSections prose={entry.prose} />}

      {entry?.updown && (entry.updown.up?.length || entry.updown.down?.length) ? (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>UPSTREAM / DOWNSTREAM</p><h2>{t.chemical.casext.updown}</h2></div></div>
          <div className="casext-updown">
            {entry.updown.up?.length ? (
              <div><h3>{t.chemical.casext.upstream}</h3><div className="casext-tags">{entry.updown.up.map((n) => <span key={`u-${n}`} className="casext-tag">{n}</span>)}</div></div>
            ) : null}
            {entry.updown.down?.length ? (
              <div><h3>{t.chemical.casext.downstream}</h3><div className="casext-tags">{entry.updown.down.map((n) => <span key={`d-${n}`} className="casext-tag">{n}</span>)}</div></div>
            ) : null}
          </div>
        </section>
      ) : null}

      {entry?.reagents && entry.reagents.length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>REAGENTS</p><h2>{t.chemical.casext.reagents}</h2></div></div>
          <div className="casext-prose-list">
            {entry.reagents.map((r) => (
              <p key={r.vendor}><strong>{r.vendor}</strong>{r.text}</p>
            ))}
          </div>
        </section>
      )}

      {suppliers && suppliers.length > 0 && (
        <section className="casext-section" id="cas-suppliers">
          <div className="section-heading compact-heading">
            <div><p>SUPPLIERS</p><h2>{t.chemical.casext.suppliers}</h2></div>
            <span>{new Intl.NumberFormat("zh-CN").format(suppliers.length)} {t.chemical.casext.supplierUnit}</span>
          </div>
          <div className="casext-suppliers">
            {suppliers.map((s) => <SupplierCard key={s.ref} supplier={s} />)}
          </div>
        </section>
      )}
    </>
  );
}

/** prose 小节按原生区块名分组渲染(应用领域/制备/FAQ/毒性/包装/安全特性)。 */
function CasProseSections({ prose }: { prose: { title: string; text: string }[] }) {
  const groups = new Map<string, { title: string; text: string }[]>();
  for (const item of prose) {
    const groupTitle = PROSE_GROUP_TITLES[item.title] ?? null;
    if (groupTitle) {
      const list = groups.get(groupTitle) ?? [];
      list.push(item);
      groups.set(groupTitle, list);
    } else {
      // 安全特性等 KV 型散文小节(标题非固定分组): 归入安全特性组
      const list = groups.get(t.chemical.casext.safetyNotes) ?? [];
      list.push(item);
      groups.set(t.chemical.casext.safetyNotes, list);
    }
  }
  if (groups.size === 0) return null;
  return (
    <>
      {Array.from(groups.entries()).map(([groupTitle, items]) => (
        <section key={groupTitle} className="casext-section">
          <div className="section-heading compact-heading"><div><p>REFERENCE</p><h2>{groupTitle}</h2></div></div>
          <div className="casext-prose-list">
            {items.map((item) => (
              <p key={item.title}><strong>{item.title}</strong>{item.text}</p>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

function SupplierCard({ supplier }: { supplier: CasSupplier }) {
  const { name, phone, email, website, purity, pack_price, remark } = supplier;
  return (
    <article className="casext-supplier">
      <header>
        <h3>{name}</h3>
      </header>
      <dl>
        {purity && <div><dt>{t.chemical.casext.purity}</dt><dd>{purity}</dd></div>}
        {pack_price && <div><dt>{t.chemical.casext.packPrice}</dt><dd>{pack_price}</dd></div>}
        {phone && <div><dt>{t.chemical.casext.phone}</dt><dd>{phone}</dd></div>}
        {email && <div><dt>{t.chemical.casext.email}</dt><dd>{email}</dd></div>}
        {website && (
          <div><dt>{t.chemical.casext.website}</dt><dd>
            <a href={website.startsWith("http") ? website : `https://${website}`} target="_blank" rel="nofollow noopener noreferrer">{website}</a>
          </dd></div>
        )}
        {remark && <div><dt>{t.chemical.casext.remark}</dt><dd>{remark}</dd></div>}
      </dl>
    </article>
  );
}
