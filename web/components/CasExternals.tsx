import t from "@/lib/i18n";

/**
 * CB 记录渲染(0905 canonical schema 重构)。
 * entry 分区: identity / props / safety / price / updown / prose。
 * 数据键即规范键; 无兼容层。界面铬文案走 t(), 数据原生内容不进语言包。
 */

export type CasIdentity = {
  cn?: string;
  en?: string;
  alias_cn?: string[];
  alias_en?: string[];
  formula?: string;
  mw?: number;
};

export type CasProp = {
  key: string;
  label: string;
  text: string;
  v?: number;
  unit?: string;
};

export type CasEntry = {
  identity?: CasIdentity;
  props?: CasProp[];
  safety?: Record<string, string>;
  price?: { updated: string; code: string; name: string; cas: string; package: string; price: string }[];
  updown?: { up?: { name: string; cb_number?: string }[]; down?: { name: string; cb_number?: string }[] };
  prose?: { title: string; text: string }[];
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

/** prose 小节按语义分组(标题白名单在解析层, 这里只分组展示)。 */
const PROSE_GROUPS: [RegExp, string][] = [
  [/^(用途|应用|概述|简介|主要应用)$/, "uses"],
  [/^(生产方法|制备)$/, "preparation"],
  [/^(化学性质|性状)$/, "properties"],
  [/^(毒性|毒性分级|急性毒性|刺激数据|职业标准)$/, "toxicity"],
  [/^(储运特性|可燃性危险特性|爆炸物危险特性|灭火剂|类别)$/, "packaging"],
];

function proseGroup(title: string): string {
  for (const [pat, group] of PROSE_GROUPS) {
    if (pat.test(title)) return group;
  }
  return "notes";
}

/** 形态防御: 旧 schema 行(重抓前)的数组形态条目不渲染, 等重抓覆盖。 */
const isProp = (p: unknown): p is CasProp =>
  !!p && typeof p === "object" && typeof (p as CasProp).key === "string" && typeof (p as CasProp).text === "string";
const isNamed = (n: unknown): n is { name: string; cb_number?: string } =>
  !!n && typeof n === "object" && typeof (n as { name: string }).name === "string";
const isProse = (i: unknown): i is { title: string; text: string } =>
  !!i && typeof i === "object" && typeof (i as { title: string }).title === "string" && typeof (i as { text: string }).text === "string";
const isPriceRow = (r: unknown): r is { updated: string; code: string; name: string; cas: string; package: string; price: string } =>
  !!r && typeof r === "object" && typeof (r as { code: string }).code === "string";

export function CasExternals({ payload }: { payload: CasExternalsPayload | null }) {
  const { entry, suppliers } = payload ?? { entry: null, suppliers: [] };
  if (!entry && (!suppliers || suppliers.length === 0)) return null; // 无数据整块不渲染

  const identity = entry?.identity && typeof entry.identity === "object" && !Array.isArray(entry.identity) ? entry.identity : undefined;
  const props = (entry?.props ?? []).filter(isProp);
  const safety = entry?.safety && !Array.isArray(entry.safety) ? entry.safety : undefined;
  const price = (entry?.price ?? []).filter(isPriceRow);
  const prose = (entry?.prose ?? []).filter(isProse);
  const up = (entry?.updown?.up ?? []).filter(isNamed);
  const down = (entry?.updown?.down ?? []).filter(isNamed);
  const hasAlias = Boolean(identity && ((identity.alias_cn && identity.alias_cn.length) || (identity.alias_en && identity.alias_en.length)));

  return (
    <>
      {identity && (identity.cn || identity.en || identity.formula || identity.mw) && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>IDENTITY</p><h2>{t.chemical.casext.identity}</h2></div></div>
          <dl className="identity-table">
            {identity.cn && <div><dt>{t.chemical.casext.nameCn}</dt><dd>{identity.cn}</dd></div>}
            {identity.en && <div><dt>{t.chemical.casext.nameEn}</dt><dd>{identity.en}</dd></div>}
            {identity.formula && <div><dt>{t.chemical.casext.formula}</dt><dd>{identity.formula}</dd></div>}
            {identity.mw != null && <div><dt>{t.chemical.casext.mw}</dt><dd>{identity.mw}</dd></div>}
          </dl>
        </section>
      )}

      {hasAlias && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>ALIASES</p><h2>{t.chemical.casext.aliases}</h2></div></div>
          <div className="casext-tags">
            {identity?.alias_cn?.map((name) => <span key={`cn-${name}`} className="casext-tag">{name}</span>)}
            {identity?.alias_en?.map((name) => <span key={`en-${name}`} className="casext-tag en">{name}</span>)}
          </div>
        </section>
      )}

      {props.length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>PROPERTIES</p><h2>{t.chemical.casext.props}</h2></div></div>
          <dl className="identity-table">
            {props.map((p) => (
              <div key={p.key}><dt>{p.label}</dt><dd>{p.v != null ? `${p.v}${p.unit ? ` ${p.unit}` : ""} · ${p.text}` : p.text}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {safety && Object.keys(safety).length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>SAFETY</p><h2>{t.chemical.casext.safety}</h2></div></div>
          <dl className="identity-table">
            {Object.entries(safety).map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {price.length > 0 && (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>PRICE</p><h2>{t.chemical.casext.price}</h2></div></div>
          <dl className="identity-table">
            {price.map((r) => (
              <div key={r.code}><dt>{r.code} · {r.package}</dt><dd>{r.name} — {r.price}</dd></div>
            ))}
          </dl>
        </section>
      )}

      {prose.length > 0 && <CasProseSections prose={prose} />}

      {(up.length || down.length) ? (
        <section className="casext-section">
          <div className="section-heading compact-heading"><div><p>UPSTREAM / DOWNSTREAM</p><h2>{t.chemical.casext.updown}</h2></div></div>
          <div className="casext-updown">
            {up.length ? (
              <div><h3>{t.chemical.casext.upstream}</h3><div className="casext-tags">{up.map((n) => <span key={`u-${n.name}`} className="casext-tag">{n.name}</span>)}</div></div>
            ) : null}
            {down.length ? (
              <div><h3>{t.chemical.casext.downstream}</h3><div className="casext-tags">{down.map((n) => <span key={`d-${n.name}`} className="casext-tag">{n.name}</span>)}</div></div>
            ) : null}
          </div>
        </section>
      ) : null}

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

/** prose 小节按语义分组渲染。 */
function CasProseSections({ prose }: { prose: { title: string; text: string }[] }) {
  const groupTitles: Record<string, string> = {
    uses: t.chemical.casext.uses,
    preparation: t.chemical.casext.preparation,
    properties: t.chemical.casext.chemicalProps,
    toxicity: t.chemical.casext.toxicity,
    packaging: t.chemical.casext.packaging,
    notes: t.chemical.casext.safetyNotes,
  };
  const groups = new Map<string, { title: string; text: string }[]>();
  for (const item of prose) {
    const g = proseGroup(item.title);
    const list = groups.get(g) ?? [];
    list.push(item);
    groups.set(g, list);
  }
  if (groups.size === 0) return null;
  return (
    <>
      {Array.from(groups.entries()).map(([g, items]) => (
        <section key={g} className="casext-section">
          <div className="section-heading compact-heading"><div><p>REFERENCE</p><h2>{groupTitles[g]}</h2></div></div>
          <div className="casext-prose-list">
            {items.map((item) => (
              <p key={item.title + item.text.slice(0, 24)}><strong>{item.title}</strong>{item.text}</p>
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
