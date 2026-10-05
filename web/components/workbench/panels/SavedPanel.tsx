"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { resolveChemicalName } from "@/lib/chemicalName";
import { WbEmpty, Pagination, PanelError, PanelHeading, PanelLoading, ReactionCards } from "../shared";
import type { ChemicalFollow, LoadState, PageResponse, PanelProps, Reaction, SavedKind } from "../types";

const emptyPage = <T,>(): PageResponse<T> => ({ items: [], total: 0, page: 1, page_size: 40 });

export function SavedPanel({ kind, page, initialChemicals, initialReactions }: PanelProps & {
  kind: SavedKind;
  initialChemicals?: PageResponse<ChemicalFollow> | null;
  initialReactions?: PageResponse<Reaction> | null;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const [chemicals, setChemicals] = useState<PageResponse<ChemicalFollow>>(initialChemicals ?? emptyPage<ChemicalFollow>());
  const [savedReactions, setSavedReactions] = useState<PageResponse<Reaction>>(initialReactions ?? emptyPage<Reaction>());
  const [state, setState] = useState<LoadState>(
    (kind === "chemicals" ? initialChemicals : initialReactions) ? "ready" : "loading"
  );
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(false);

  useEffect(() => {
    if (!mounted.current && ((kind === "chemicals" && initialChemicals) || (kind === "reactions" && initialReactions))) {
      mounted.current = true; return;
    }
    mounted.current = true;
    let active = true;
    setState("loading");
    setError(null);
    if (kind === "chemicals") {
      apiGet<PageResponse<ChemicalFollow>>(`/users/me/follows/chemicals?page=${page}&page_size=40`)
        .then((value) => { if (active) { setChemicals(value); setState("ready"); } })
        .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    } else {
      apiGet<PageResponse<Reaction>>(`/users/me/follows/reactions?page=${page}&page_size=20`)
        .then((value) => { if (active) { setSavedReactions(value); setState("ready"); } })
        .catch((err: unknown) => { if (active) { setError(err); setState("error"); } });
    }
    return () => { active = false; };
  }, [kind, page]);

  const data = kind === "chemicals" ? chemicals : savedReactions;

  return (
    <section className="wb-panel">
      <PanelHeading title={t.me.tabSaved} subtitle={t.me.savedHint} count={state === "ready" ? data.total : "—"} unit={kind === "chemicals" ? t.me.unitChemical : t.me.unitReaction} />
      <nav className="wb-filters" aria-label={t.me.filterSaved}>
        <Link href="/aichem?tab=saved" className={kind === "chemicals" ? "active" : ""}>{t.search.chemicalResults}</Link>
        <Link href="/aichem?tab=saved&kind=reactions" className={kind === "reactions" ? "active" : ""}>{t.search.reactionResults}</Link>
      </nav>
      {state === "loading" && <PanelLoading variant={kind === "chemicals" ? "list" : "grid"} />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && kind === "chemicals" && (chemicals.items.length
        ? <div className="wb-followed-list">
            {chemicals.items.map((item) => (
              <Link href={withLocale(`/chemical/${item.id}`, locale)} key={item.id}>
                <EntityId kind="chemical" id={item.id} compact />
                <span><strong>{resolveChemicalName(item, t.common.hcidLabel).title}</strong>{item.smiles && <small>{item.smiles}</small>}</span>
              </Link>
            ))}
          </div>
        : <WbEmpty text={t.me.emptyChemicals} />)}
      {state === "ready" && kind === "reactions" && (savedReactions.items.length
        ? <ReactionCards items={savedReactions.items} />
        : <WbEmpty text={t.me.emptyReactionSaved} />)}
      {state === "ready" && data.total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => `/aichem?tab=saved${kind === "reactions" ? "&kind=reactions" : ""}&page=${value}`} />
      )}
    </section>
  );
}
