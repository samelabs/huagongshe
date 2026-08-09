"use client";

import Link from "next/link";
import { EntityId } from "@/components/EntityId";
import t from "@/lib/i18n";
import { DashboardEmpty, Pagination, PanelError, PanelHeading, PanelLoading, ReactionCards } from "../shared";
import type { ChemicalFollow, LoadState, PageResponse, Reaction, SavedKind } from "../types";

export function SavedPanel({ chemicals, reactions, state, kind, page }: {
  chemicals: PageResponse<ChemicalFollow>;
  reactions: PageResponse<Reaction>;
  state: LoadState;
  kind: SavedKind;
  page: number;
}) {
  const data = kind === "chemicals" ? chemicals : reactions;
  return (
    <section>
      <PanelHeading title={t.me.tabSaved} subtitle={t.me.savedHint} count={state === "ready" ? data.total : "—"} unit={kind === "chemicals" ? t.me.unitChemical : t.me.unitReaction} />
      <nav className="wb-filters" aria-label={t.me.filterSaved}>
        <Link href="/aichem?tab=saved" className={kind === "chemicals" ? "active" : ""}>{t.search.chemicalResults}</Link>
        <Link href="/aichem?tab=saved&kind=reactions" className={kind === "reactions" ? "active" : ""}>{t.search.reactionResults}</Link>
      </nav>
      {state === "loading" && <PanelLoading />}
      {state === "error" && <PanelError />}
      {state === "ready" && kind === "chemicals" && (chemicals.items.length
        ? <div className="wb-followed-list">
            {chemicals.items.map((item) => (
              <Link href={`/chemical/${item.id}`} key={item.id}>
                <EntityId kind="chemical" id={item.id} compact />
                <span><strong>{item.preferred_name || item.iupac_name || t.common.unnamedCompound}</strong>{item.smiles && <small>{item.smiles}</small>}</span>
                <em>{t.common.view}</em>
              </Link>
            ))}
          </div>
        : <DashboardEmpty text={t.me.emptyChemicals} />)}
      {state === "ready" && kind === "reactions" && (reactions.items.length
        ? <ReactionCards items={reactions.items} />
        : <DashboardEmpty text={t.me.emptyReactionSaved} />)}
      {state === "ready" && data.total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => `/aichem?tab=saved${kind === "reactions" ? "&kind=reactions" : ""}&page=${value}`} />
      )}
    </section>
  );
}
