"use client";

import { useState } from "react";
import { EntityId } from "@/components/shared/EntityId";
import { useDictionary } from "@/components/shared/I18nContext";

type Kind = "chemical" | "reaction";

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
  const [kind, setKind] = useState<Kind>("chemical");
  const [raw, setRaw] = useState("");

  function add() {
    const id = Number.parseInt(raw.trim(), 10);
    if (!Number.isSafeInteger(id) || id < 1) return;
    if (kind === "chemical") {
      if (!chemicalIds.includes(id)) onChange({ chemicalIds: [...chemicalIds, id], reactionIds });
    } else if (!reactionIds.includes(id)) {
      onChange({ chemicalIds, reactionIds: [...reactionIds, id] });
    }
    setRaw("");
  }

  function remove(target: Kind, id: number) {
    onChange({
      chemicalIds: target === "chemical" ? chemicalIds.filter((value) => value !== id) : chemicalIds,
      reactionIds: target === "reaction" ? reactionIds.filter((value) => value !== id) : reactionIds,
    });
  }

  return (
    <div className="wb-note-references">
      <div className="wb-note-reference-input">
        <select value={kind} onChange={(event) => setKind(event.target.value as Kind)} disabled={disabled}>
          <option value="chemical">HCID</option>
          <option value="reaction">HRID</option>
        </select>
        <input
          type="number"
          min="1"
          step="1"
          inputMode="numeric"
          value={raw}
          onChange={(event) => setRaw(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              add();
            }
          }}
          placeholder={kind === "chemical" ? t.me.notesChemicalPlaceholder : t.me.notesReactionPlaceholder}
          disabled={disabled}
        />
        <button type="button" className="wb-btn wb-btn-ghost" onClick={add} disabled={disabled || !raw.trim()}>
          {t.me.notesAddReference}
        </button>
      </div>
      <div className="wb-note-reference-chips">
        {chemicalIds.map((id) => (
          <button type="button" key={`c-${id}`} onClick={() => remove("chemical", id)} disabled={disabled} title={t.me.notesRemoveReference}>
            <EntityId kind="chemical" id={id} compact />
            <span aria-hidden="true">×</span>
          </button>
        ))}
        {reactionIds.map((id) => (
          <button type="button" key={`r-${id}`} onClick={() => remove("reaction", id)} disabled={disabled} title={t.me.notesRemoveReference}>
            <EntityId kind="reaction" id={id} compact />
            <span aria-hidden="true">×</span>
          </button>
        ))}
      </div>
      <small>{t.me.notesReferenceHint}</small>
    </div>
  );
}
