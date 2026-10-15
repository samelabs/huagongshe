import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { apiGet, isApiGone, isEntityId, reactionSvgUrl, type ReactionDetail, type Chemical } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { resolveChemicalName } from "@/lib/chemicalName";
import { withLocale } from "@/lib/localePath";
import "../../chemical/[id]/print/print.css";

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

function fmt(v: number | null | undefined, locale: string): string {
  if (v == null) return "—";
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 4 }).format(v);
}

export default async function ReactionPrintPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!isEntityId(id)) notFound();

  const locale = await getRequestLocale();
  const t = await getRequestDictionary();

  const reaction = await apiGet<ReactionDetail>(`/reactions/${id}`).catch((e: unknown) => {
    if (isApiGone(e)) notFound();
    return null;
  });

  if (!reaction) notFound();

  const printDate = new Intl.DateTimeFormat(locale, { dateStyle: "long" }).format(new Date());
  const pageUrl = `https://huagongshe.com${withLocale(`/reaction/${id}`, locale)}`;

  const conditionRows: [string, string][] = [
    reaction.temperature ? [t.reaction.conditionFields.temperature, `${reaction.temperature.value} ${reaction.temperature.unit}`] : null,
    reaction.duration ? [t.reaction.conditionFields.time, `${reaction.duration.value} ${reaction.duration.unit}`] : null,
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
            src={reactionSvgUrl(reaction.id, 800, 220)}
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
                  <th>{t.submit.roles ? "Role" : "Role"}</th>
                  <th>{t.common.name}</th>
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
                      <td>{p.role ?? "—"}</td>
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
                {reaction.patent && <tr><th>{t.reaction.patent}</th><td>{reaction.patent}</td></tr>}
                {reaction.dataset_name && <tr><th>{t.reaction.dataset}</th><td>{reaction.dataset_name}</td></tr>}
                {reaction.ord_id && <tr><th>ORD ID</th><td className="pr-mono">{reaction.ord_id}</td></tr>}
                {reaction.source_citation && <tr><th>{t.reaction.sourceCitation}</th><td>{reaction.source_citation}</td></tr>}
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
