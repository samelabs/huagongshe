import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { EntityId } from "@/components/shared/EntityId";
import { apiGet, isApiNotFound, type NoteItem } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag } from "@/lib/alternates";

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  const canonical = `/note/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return {
    title: `${t.notes.detailTitle} ${id}`,
    description: t.notes.detailTitle,
    // Private note content must never enter shared/public page metadata:
    // the description stays generic by design.
    alternates: localeAlternates(canonical, locale),
    openGraph: { url: withLocale(canonical, locale), title: `${t.notes.detailTitle} ${id}｜${t.brand.name}`, description: t.notes.detailTitle, locale: ogLocaleTag(locale) },
  };
}

export default async function NoteDetailPage({ params }: Params) {
  const { id } = await params;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const cookieStore = await cookies();
  const hasSession = cookieStore.has("hgs_session");
  const cookie = cookieStore.toString();
  let note: NoteItem;
  try {
    // Server-side read with the viewer session; permission matrix is enforced
    // by GET /api/notes/{id} (public anonymous / owner session; 404 otherwise).
    note = await apiGet<NoteItem>(`/notes/${id}`, hasSession ? { Cookie: cookie } : undefined);
  } catch (error) { if (isApiNotFound(error)) notFound(); throw error; }

  const authorLine = note.display_name || `@${note.username}`;
  return (
    <div className="content-page note-detail-page">
      <article className="note-detail">
        <header className="note-detail-head">
          <h1>{t.notes.detailTitle} {note.id}</h1>
          <div className="note-detail-meta">
            <span className={`note-vis-badge ${note.visibility === "public" ? "is-public" : "is-private"}`}>
              {note.visibility === "public" ? t.notes.visibilityPublic : t.notes.visibilityPrivate}
            </span>
            <Link href={withLocale(`/user/${encodeURIComponent(note.username)}`, locale)}>{authorLine}</Link>
            <time dateTime={note.updated_at}>{t.notes.updatedLabel}: {new Date(note.updated_at).toLocaleString(locale)}</time>
          </div>
        </header>
        {/* Full content: pre-wrap + overflow-wrap; no truncation on the detail page. */}
        <div className="note-detail-content">{note.content}</div>
        {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
          <div className="entity-note-links note-detail-links">
            {note.chemical_ids.map((cid) => (
              <Link key={`c-${cid}`} href={withLocale(`/chemical/${cid}`, locale)}><EntityId kind="chemical" id={cid} compact /></Link>
            ))}
            {note.reaction_ids.map((rid) => (
              <Link key={`r-${rid}`} href={withLocale(`/reaction/${rid}`, locale)}><EntityId kind="reaction" id={rid} compact /></Link>
            ))}
          </div>
        )}
      </article>
    </div>
  );
}
