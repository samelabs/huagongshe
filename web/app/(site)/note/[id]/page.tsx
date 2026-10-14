import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { NoteOwnerActions } from "@/components/NoteOwnerActions";
import { Avatar } from "@/components/ui/Avatar";
import { Breadcrumb } from "@/components/ui/Breadcrumb";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { IconLock } from "@/components/ui/icons";
import { Tag } from "@/components/ui/Tag";
import { apiGet, isApiNotFound, isApiGone, isEntityId, type NoteItem } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeAlternates, ogLocaleTag } from "@/lib/alternates";

import { buildShareMetadata } from "@/lib/shareMeta";
import { WeChatMeta } from "@/components/shared/WeChatMeta";

type Params = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  // FX-3（SMK-002）：非法 ID 与页面同一口径 → 404
  if (!isEntityId(id)) notFound();
  const canonical = `/note/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const pageTitle = `${t.notes.detailTitle} ${id}`;
  const description = t.notes.detailTitle;
  const shareMeta = buildShareMetadata({
    title: `${pageTitle}｜${t.brand.name}`,
    description,
    path: canonical,
    locale,
    siteName: t.brand.name,
    ogImage: {
      url: "/og.png",
      width: 1200,
      height: 630,
      alt: t.brand.ogAlt,
    },
    itempropImage: "/icon-512.png",
    twitterCard: "summary_large_image",
  });
  return {
    title: pageTitle,
    description,
    alternates: localeAlternates(canonical, locale),
    ...shareMeta,
  };
}

/** 笔记标题与正文（DESIGN_SYSTEM 6.5 / I-043）：
 *  标题取正文首行（≤60 字超出省略号）；
 *  首行之后的内容作为正文排在页面上；
 *  若只有一行且超过 60 字，正文显示完整内容避免文字丢失。 */
function extractNoteTitleAndBody(content: string, id: number, fallback: string): { title: string; body: string } {
  const lines = content.split("\n");
  let firstIdx = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].trim().length > 0) {
      firstIdx = i;
      break;
    }
  }
  if (firstIdx === -1) {
    return { title: `${fallback} ${id}`, body: "" };
  }
  const firstLine = lines[firstIdx].trim();
  const isTruncated = firstLine.length > 60;
  const title = isTruncated ? `${firstLine.slice(0, 60)}…` : firstLine;
  const afterFirstLine = lines.slice(firstIdx + 1).join("\n").trim();
  const body = afterFirstLine || (isTruncated ? firstLine : "");
  return { title, body };
}

export default async function NoteDetailPage({ params }: Params) {
  const { id } = await params;
  // FX-3（SMK-002 / HGS-WEB-DETAIL-ID-01）：非法 ID 直接 404；后端 422 同 404
  if (!isEntityId(id)) notFound();
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
  } catch (error) {
    // 404（无此笔记/无权限）与 422（ID 非法）同道落 404 页；
    // isApiNotFound 为 P1C 隐私契约键（私有笔记按 404 呈现，不泄漏存在性）
    if (isApiNotFound(error) || isApiGone(error)) notFound();
    throw error;
  }

  const authorLine = note.display_name || `@${note.username}`;
  const { title, body } = extractNoteTitleAndBody(note.content, note.id, t.notes.detailTitle);
  const hasLinkedEntities = note.chemical_ids.length > 0 || note.reaction_ids.length > 0;

  return (
    <div className="content-page note-detail-page">
      <WeChatMeta name={`${title}｜${t.brand.name}`} description={t.notes.detailTitle} image="/icon-512.png" />
      <Breadcrumb
        items={[
          { label: t.chemical.home, href: withLocale("/", locale) },
          { label: t.notes.category },
          { label: title },
        ]}
        ariaLabel={t.common.breadcrumb}
      />
      <article className="note-detail">
        <header className="note-detail-head">
          <h1>{title}</h1>
          <div className="note-detail-meta">
            <Avatar id={note.owner_user_id} name={authorLine} size={24} />
            <Link href={withLocale(`/user/${encodeURIComponent(note.username)}`, locale)}>{authorLine}</Link>
            {/* HGS-ACCOUNT-CONTENT-01: 停用作者的公开笔记保留可见，作者名旁带「已停用」 */}
            {note.owner_active === false && <Tag tone="neutral" dot>{t.user.authorDeactivated}</Tag>}
            <time dateTime={note.updated_at}>{new Date(note.updated_at).toLocaleDateString(locale)}</time>
            {note.visibility === "public"
              ? <Tag tone="blue">{t.notes.visibilityPublic}</Tag>
              : <Tag icon={<IconLock />}>{t.notes.visibilityPrivate}</Tag>}
          </div>
        </header>

        {hasLinkedEntities && (
          <div className="note-detail-links entity-note-links">
            {note.chemical_ids.map((cid) => (
              <EntityBadge
                key={`c-${cid}`}
                kind="chemical"
                id={cid}
                size="xs"
                href={withLocale(`/chemical/${cid}`, locale)}
                ariaLabel={t.common.hcidLabel(cid)}
              />
            ))}
            {note.reaction_ids.map((rid) => (
              <EntityBadge
                key={`r-${rid}`}
                kind="reaction"
                id={rid}
                size="xs"
                href={withLocale(`/reaction/${rid}`, locale)}
                ariaLabel={t.common.hridLabel(rid)}
              />
            ))}
          </div>
        )}

        {/* Full content: pre-wrap + overflow-wrap; no truncation on the detail page.
            多行笔记的标题行（第一行）不重复出现在正文里。 */}
        {body && <div className="note-detail-content">{body}</div>}

        {/* 本人操作：编辑（secondary）、删除（danger-quiet） */}
        {hasSession && (
          <NoteOwnerActions noteId={note.id} ownerUsername={note.username} excerpt={note.content.slice(0, 24)} />
        )}
      </article>
    </div>
  );
}

