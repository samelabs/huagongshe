import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { NoteOwnerActions } from "@/components/NoteOwnerActions";
import { Avatar } from "@/components/ui/Avatar";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { IconLock } from "@/components/ui/icons";
import { Tag } from "@/components/ui/Tag";
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

/** 笔记标题（Step 8 Part A）：
 *  - 正文只有一行（非空行计）→「笔记 · 2026/10/10」（本地化日期），不重复正文；
 *  - 两行及以上 → 第一行作标题（≤60 字超出省略号），正文从第二行开始显示。
 *  第一行为空退回「笔记 {id}」；<title>/meta 保持 generic，不入正文。 */
function noteTitle(content: string, id: number, fallback: string): string {
  const lines = content.split("\n").map((l) => l.trim()).filter((l) => l.length > 0);
  if (lines.length === 0) return `${fallback} ${id}`;
  if (lines.length === 1) return "";
  const firstLine = lines[0];
  return firstLine.length > 60 ? `${firstLine.slice(0, 60)}…` : firstLine;
}

/** 「笔记 · 本地化日期」标题（单行正文的标题形态） */
function noteDateTitle(fallback: string, updatedAt: string, locale: string): string {
  const date = new Intl.DateTimeFormat(locale, { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(updatedAt));
  return `${fallback} · ${date}`;
}

/** 两行及以上时，正文从第二行开始显示：截掉首个非空行（标题行）之前与该行本身。 */
function contentAfterFirstLine(content: string): string {
  const lines = content.split("\n");
  let index = 0;
  while (index < lines.length && lines[index].trim().length === 0) index += 1;
  if (index >= lines.length) return content;
  return lines.slice(index + 1).join("\n");
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
  const singleLineTitle = noteTitle(note.content, note.id, t.notes.detailTitle);
  const title = singleLineTitle || noteDateTitle(t.notes.detailTitle, note.updated_at, locale);
  const bodyContent = singleLineTitle ? contentAfterFirstLine(note.content) : note.content;

  return (
    <div className="content-page note-detail-page">
      <article className="note-detail">
        <header className="note-detail-head">
          <h1>{title}</h1>
          <div className="note-detail-meta">
            <Avatar id={note.owner_user_id} name={authorLine} size={24} />
            <Link href={withLocale(`/user/${encodeURIComponent(note.username)}`, locale)}>{authorLine}</Link>
            <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time>
            {note.visibility === "public"
              ? <Tag tone="blue">{t.notes.visibilityPublic}</Tag>
              : <Tag icon={<IconLock />}>{t.notes.visibilityPrivate}</Tag>}
          </div>
          {/* 本人操作：NoteOwnerActions 用全局会话比对作者 username，非本人隐藏 */}
          {hasSession && <NoteOwnerActions noteId={note.id} ownerUsername={note.username} excerpt={note.content.slice(0, 24)} />}
        </header>
        {/* Full content: pre-wrap + overflow-wrap; no truncation on the detail page.
            多行笔记的标题行（第一行）不重复出现在正文里。 */}
        <div className="note-detail-content">{bodyContent}</div>
        {(note.chemical_ids.length > 0 || note.reaction_ids.length > 0) && (
          <div className="note-detail-links">
            <h2 className="note-links-title">{t.notes.linkedLabel}</h2>
            <div className="entity-note-links">
              {note.chemical_ids.map((cid) => (
                <Link key={`c-${cid}`} href={withLocale(`/chemical/${cid}`, locale)}><EntityBadge kind="chemical" id={cid} size="sm" ariaLabel={t.common.hcidLabel(cid)} /></Link>
              ))}
              {note.reaction_ids.map((rid) => (
                <Link key={`r-${rid}`} href={withLocale(`/reaction/${rid}`, locale)}><EntityBadge kind="reaction" id={rid} size="sm" ariaLabel={t.common.hridLabel(rid)} /></Link>
              ))}
            </div>
          </div>
        )}
      </article>
    </div>
  );
}
