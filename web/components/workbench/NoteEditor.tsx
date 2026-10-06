"use client";

import { useState } from "react";
import { apiPost, apiPut, ApiError } from "@/lib/api";
import { useDictionary } from "@/components/shared/I18nContext";
import { EntityReferencePicker } from "./EntityReferencePicker";
import type { NoteItem } from "./types";

export function NoteEditor({
  note,
  initialChemicalIds = [],
  initialReactionIds = [],
  onSaved,
  onCancel,
}: {
  note?: NoteItem | null;
  initialChemicalIds?: number[];
  initialReactionIds?: number[];
  onSaved: (note: NoteItem) => void;
  onCancel: () => void;
}) {
  const t = useDictionary();
  const [visibility, setVisibility] = useState<"private" | "public">(note?.visibility ?? "private");
  const [content, setContent] = useState(note?.content ?? "");
  const [chemicalIds, setChemicalIds] = useState<number[]>(note?.chemical_ids ?? initialChemicalIds);
  const [reactionIds, setReactionIds] = useState<number[]>(note?.reaction_ids ?? initialReactionIds);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = {
      visibility,
      content: content.trim(),
      chemical_ids: chemicalIds,
      reaction_ids: reactionIds,
    };
    if (!body.content) return;
    setBusy(true);
    setError("");
    try {
      const saved = note
        ? await apiPut<NoteItem>(`/notes/${note.id}`, JSON.stringify(body))
        : await apiPost<NoteItem>("/notes", JSON.stringify(body));
      onSaved(saved);
    } catch (err) {
      setError(err instanceof ApiError && err.detail ? err.detail : t.me.notesSaveFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="wb-note-editor" onSubmit={save}>
      <div className="wb-note-editor-head">
        <strong>{note ? t.me.notesEdit : t.me.notesNew}</strong>
        <select value={visibility} onChange={(event) => setVisibility(event.target.value as "private" | "public")} disabled={busy}>
          <option value="private">{t.common.private}</option>
          <option value="public">{t.common.public}</option>
        </select>
      </div>
      <textarea
        rows={8}
        maxLength={30000}
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder={t.me.notesPlaceholder}
        autoFocus
        disabled={busy}
      />
      <EntityReferencePicker
        chemicalIds={chemicalIds}
        reactionIds={reactionIds}
        onChange={({ chemicalIds: nextChemicals, reactionIds: nextReactions }) => {
          setChemicalIds(nextChemicals);
          setReactionIds(nextReactions);
        }}
        disabled={busy}
      />
      {error && <p className="wb-note-error">{error}</p>}
      <div className="wb-note-editor-actions">
        <button type="button" className="wb-btn wb-btn-ghost" onClick={onCancel} disabled={busy}>{t.common.cancel}</button>
        <button type="submit" className="wb-btn wb-btn-primary" disabled={busy || !content.trim()}>
          {busy ? t.me.notesSaving : t.me.notesSave}
        </button>
      </div>
    </form>
  );
}
