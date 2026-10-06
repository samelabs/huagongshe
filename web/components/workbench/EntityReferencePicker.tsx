"use client";

import { useState } from "react";
import { EntityId } from "@/components/shared/EntityId";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { apiGet, type SearchResponse } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";

const MAX_REFERENCES = 20;

export function EntityReferencePicker({
  chemicalIds,
  reactionIds,
  onChange,
  disabled = false,
}: {
  chemicalIds: number[];
  reactionIds: number[];
  onChange: (value: { chemicalIds: number[]; reactionIds: number[] }) => void;
  disabled?: boolean;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const total = chemicalIds.length + reactionIds.length;

  async function search(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = query.trim();
    if (!q || disabled) return;
    setSearching(true);
    setError("");
    try {
      setResults(await apiGet<SearchResponse>(
        `/search?q=${encodeURIComponent(q)}&mode=exact&page=1&page_size=8`
      ));
    } catch {
      setError(t.me.notesReferenceSearchFailed);
      setResults(null);
    } finally {
      setSearching(false);
    }
  }

  function add(kind: "chemical" | "reaction", id: number) {
    if (disabled || total >= MAX_REFERENCES) return;
    if (kind === "chemical") {
      if (!chemicalIds.includes(id)) {
        onChange({ chemicalIds: [...chemicalIds, id], reactionIds });
      }
    } else if (!reactionIds.includes(id)) {
      onChange({ chemicalIds, reactionIds: [...reactionIds, id] });
    }
  }

  function remove(kind: "chemical" | "reaction", id: number) {
    onChange({
      chemicalIds: kind === "chemical"
        ? chemicalIds.filter((value) => value !== id)
        : chemicalIds,
      reactionIds: kind === "reaction"
        ? reactionIds.filter((value) => value !== id)
        : reactionIds,
    });
  }

  const hasResults = Boolean(
    results && (results.chemicals.length > 0 || (results.reactions?.length ?? 0) > 0)
  );

  return (
    <div className="wb-note-references">
      <form className="wb-note-reference-input" onSubmit={search}>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={t.me.notesReferenceSearchPlaceholder}
          disabled={disabled}
          autoComplete="off"
          spellCheck={false}
        />
        <button type="submit" className="wb-btn wb-btn-ghost"
          disabled={disabled || searching || !query.trim()}>
          {searching ? t.common.loading : t.me.notesReferenceSearch}
        </button>
      </form>

      {error && <p className="wb-note-error">{error}</p>}
      {results && !hasResults && <small>{t.me.notesReferenceNoResults}</small>}

      {hasResults && (
        <div className="wb-note-reference-results">
          {results!.chemicals.map((chemical) => {
            const selected = chemicalIds.includes(chemical.id);
            const name = resolveChemicalName(chemical, t.common.hcidLabel, locale).title;
            return (
              <button type="button" key={`c-${chemical.id}`}
                onClick={() => add("chemical", chemical.id)}
                disabled={disabled || selected || total >= MAX_REFERENCES}>
                <span><strong>{name}</strong><small>{chemical.molecular_formula || chemical.inchikey || ""}</small></span>
                <EntityId kind="chemical" id={chemical.id} compact />
                <em>{selected ? t.me.notesReferenceAdded : t.me.notesAddReference}</em>
              </button>
            );
          })}
          {(results!.reactions || []).map((reaction) => {
            const selected = reactionIds.includes(reaction.id);
            return (
              <button type="button" key={`r-${reaction.id}`}
                onClick={() => add("reaction", reaction.id)}
                disabled={disabled || selected || total >= MAX_REFERENCES}>
                <span><strong><EntityId kind="reaction" id={reaction.id} compact /></strong>
                  <small>{reaction.doi || reaction.ord_id || reaction.dataset_name || ""}</small></span>
                <em>{selected ? t.me.notesReferenceAdded : t.me.notesAddReference}</em>
              </button>
            );
          })}
        </div>
      )}

      <div className="wb-note-reference-chips">
        {chemicalIds.map((id) => (
          <button type="button" key={`selected-c-${id}`} onClick={() => remove("chemical", id)}
            disabled={disabled} title={t.me.notesRemoveReference}>
            <EntityId kind="chemical" id={id} compact /><span aria-hidden="true">×</span>
          </button>
        ))}
        {reactionIds.map((id) => (
          <button type="button" key={`selected-r-${id}`} onClick={() => remove("reaction", id)}
            disabled={disabled} title={t.me.notesRemoveReference}>
            <EntityId kind="reaction" id={id} compact /><span aria-hidden="true">×</span>
          </button>
        ))}
      </div>
      <small>{total >= MAX_REFERENCES ? t.me.notesReferenceLimit : t.me.notesReferenceHint}</small>
    </div>
  );
}
