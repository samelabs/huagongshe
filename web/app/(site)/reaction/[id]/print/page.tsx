import type { Metadata } from "next";
import Link from "next/link";
import { PrintButton } from "@/components/PrintButton";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { apiGet, isApiGone, isEntityId, reactionSvgUrl, type ReactionDetail, type Chemical } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import "@/app/(site)/chemical/[id]/print/print.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

function fmt(v: number | null | undefined, locale: string): string {
  if (v == null) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(v);
}

/** 与详情页同款单位/角色本地化(枚举值不直接进报告)。 */
function unitName(value: string, t: Dictionary): string {
  const labels: Record<string, string> = {
    CELSIUS: "°C", KELVIN: "K",
    MINUTE: t.reaction.timeUnits.minute, HOUR: t.reaction.timeUnits.hour, DAY: t.reaction.timeUnits.day,
  };
  return labels[value] || value.replaceAll("_", " ").toLowerCase();
}

function roleLabel(role: string | null | undefined, t: Dictionary): string {
  const labels: Record<string, string> = {
    REACTANT: t.submit.roles.reactant, REAGENT: t.submit.roles.reagent,
    CATALYST: t.submit.roles.catalyst, SOLVENT: t.submit.roles.solvent,
    PRODUCT: t.submit.roles.product, WORKUP: t.reaction.workup,
    INTERNAL_STANDARD: t.reaction.internalStandard,
  };
  if (!role) return "—";
  return labels[role] || role.replaceAll("_", " ").toLowerCase();
}

export default async function ReactionPrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isEntityId(id)) notFound();

  const locale = await getRequestLocale();
  const t = await getRequestDictionary();

  // 与详情页同范式：带会话 Cookie 取反应 —— 作者打印自己的私有反应不能按匿名处理
  const cookieStore = await cookies();
  const cookie = cookieStore.toString();
  const reaction = await apiGet<ReactionDetail>(`/reactions/${id}`, cookieStore.has("hgs_session") ? { Cookie: cookie } : undefined).catch((e: unknown) => {
    if (isApiGone(e)) notFound();
    return null;
  });

  if (!reaction) notFound();

  const printDate = new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date());
  const pageUrl = `https://huagongshe.com${withLocale(`/reaction/${id}`, locale)}`;

  const conditionRows: [string, string][] = [
    reaction.temperature ? [t.reaction.conditionFields.temperature, `${reaction.temperature.value} ${unitName(reaction.temperature.unit, t)}`] : null,
    reaction.duration ? [t.reaction.conditionFields.time, `${reaction.duration.value} ${unitName(reaction.duration.unit, t)}`] : null,
    reaction.atmosphere ? [t.reaction.conditionFields.atmosphere, reaction.atmosphere] : null,
    reaction.pressure ? [t.reaction.conditionFields.pressure, `${reaction.pressure.value} ${reaction.pressure.unit}`] : null,
    reaction.ph != null ? ["pH", String(reaction.ph)] : null,
    reaction.reflux ? [t.reaction.conditionFields.reflux, "✓"] : null,
  ].filter(Boolean) as [string, string][];

  return (
    <div className="pr-root">
      {/* ── Toolbar ── */}
      <div className="pr-toolbar no-print">
        <button
          className="pr-btn"
          data-print-btn="true"
          suppressHydrationWarning
        >
          {t.print.printAction}
        </button>
        <Link href={withLocale(`/reaction/${id}`, locale)} className="pr-btn pr-btn-ghost">
          {t.print.backAction}
        </Link>
      </div>

      <article className="pr-page">
        {/* Report header */}
        <header className="pr-report-head">
          <div className="pr-logo-row">
            <span className="pr-brand">{t.brand.name}</span>
            <span className="pr-notice">{t.print.reportNotice}</span>
          </div>
          <div className="pr-meta-row">
            <span className="pr-hcid">{t.common.hridLabel(id)}</span>
            <span className="pr-date">{t.print.generatedAt(printDate)}</span>
          </div>
          <h1 className="pr-title">{t.print.reactionReportTitle}</h1>
          <p className="pr-url"><a href={pageUrl}>{pageUrl}</a></p>
        </header>

        {/* Reaction SVG */}
        <section className="pr-section pr-structure-section">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={reactionSvgUrl(reaction.id)}
            alt={t.reaction.equation}
            className="pr-reaction-svg"
          />
        </section>

        {/* Participants */}
        {reaction.participants.length > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.participants}</h2>
            <table className="pr-participants-table">
              <thead>
                <tr>
                  <th>{t.stoich.colRole}</th>
                  <th>{t.print.colName}</th>
                  <th>HCID</th>
                  <th>{t.submit.amount}</th>
                </tr>
              </thead>
              <tbody>
                {reaction.participants.map((p: Chemical) => {
                  const { title: pName } = resolveChemicalName(p, t.common.hcidLabel, locale);
                  const amount = [
                    p.amount_value != null ? `${fmt(p.amount_value, locale)} ${p.amount_unit ?? ""}`.trim() : null,
                    p.equivalents != null ? `${fmt(p.equivalents, locale)} eq` : null,
                    p.yield_percent != null ? `${fmt(p.yield_percent, locale)}%` : null,
                  ].filter(Boolean).join(", ");
                  return (
                    <tr key={p.id}>
                      <td>{roleLabel(p.role, t)}</td>
                      <td>{pName}</td>
                      <td className="pr-mono">{t.common.hcidLabel(p.id)}</td>
                      <td>{amount || "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        )}

        {/* Conditions */}
        {conditionRows.length > 0 && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.conditions}</h2>
            <table className="pr-table">
              <tbody>
                {conditionRows.map(([label, val]) => (
                  <tr key={label}>
                    <th>{label}</th>
                    <td>{val}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
        {reaction.conditions_detail && (
          <section className="pr-section">
            <p className="pr-prose-text">{reaction.conditions_detail}</p>
          </section>
        )}

        {/* Procedure */}
        {reaction.procedure_details && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.steps}</h2>
            <p className="pr-prose-text">{reaction.procedure_details}</p>
          </section>
        )}

        {/* Workup */}
        {reaction.workup_details && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.reaction.workup}</h2>
            <p className="pr-prose-text">{reaction.workup_details}</p>
          </section>
        )}

        {/* Safety */}
        {reaction.safety_notes && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.safety}</h2>
            <p className="pr-prose-text">{reaction.safety_notes}</p>
          </section>
        )}

        {/* Provenance */}
        {(reaction.doi || reaction.patent || reaction.source_citation || reaction.dataset_name) && (
          <section className="pr-section">
            <h2 className="pr-section-h">{t.print.provenance}</h2>
            <table className="pr-table">
              <tbody>
                {reaction.doi && <tr><th>DOI</th><td>{reaction.doi}</td></tr>}
                {reaction.patent && <tr><th>{t.reaction.sourceFields.patent}</th><td>{reaction.patent}</td></tr>}
                {reaction.dataset_name && <tr><th>{t.reaction.sourceFields.dataset}</th><td>{reaction.dataset_name}</td></tr>}
                {reaction.ord_id && <tr><th>ORD ID</th><td className="pr-mono">{reaction.ord_id}</td></tr>}
                {reaction.source_citation && <tr><th>{t.reaction.sourceFields.note}</th><td>{reaction.source_citation}</td></tr>}
              </tbody>
            </table>
          </section>
        )}
      </article>

      <script
        dangerouslySetInnerHTML={{
          __html: `document.querySelectorAll('[data-print-btn]').forEach(function(b){b.addEventListener('click',function(){window.print();});});`,
        }}
      />
    </div>
  );
}
