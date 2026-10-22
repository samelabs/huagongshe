import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cookies } from "next/headers";
import { NoteOwnerActions } from "@/components/NoteOwnerActions";
import { ShareButton } from "@/components/ShareButton";
import { Byline } from "@/components/ui/Byline";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { IconLock } from "@/components/ui/icons";
import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";
import { Tag } from "@/components/ui/Tag";
import Link from "next/link";
import { apiGet } from "@/lib/api.server";
import { isApiNotFound, isApiGone, type Chemical, type NoteItem } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";
import { localeAlternates } from "@/lib/alternates";
import { resolveChemicalName } from "@/lib/chemicalName";
import { resolveNotePresentation } from "@/lib/noteHeadline";
import { buildShareMetadata } from "@/lib/shareMeta";

type Params = { params: Promise<{ id: string }> };

/** URL ref: 7 位 slug —— 笔记唯一公共标识。 */
function isNoteRef(value: string): boolean {
  return /^[a-z0-9]{7}$/.test(value);
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { id } = await params;
  if (!isNoteRef(id)) notFound();
  let canonical = `/note/${id}`;
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  let pageTitle = `${t.notes.detailTitle} ${id}`;
  let description = t.notes.detailTitle;

  try {
    const note = await apiGet<NoteItem>(`/notes/${id}`);
    const authorLine = note.display_name || `@${note.username}`;
    let entityName: string | null = null;
    if (note.chemical_ids.length > 0) {
      try {
        const chem = await apiGet<Chemical>(`/chemicals/${note.chemical_ids[0]}`);
        entityName = resolveChemicalName(chem, t.common.hcidLabel, locale).title;
      } catch {
        entityName = t.common.hcidLabel(note.chemical_ids[0]);
      }
    } else if (note.reaction_ids.length > 0) {
      entityName = t.common.hridLabel(note.reaction_ids[0]);
    }
    const pres = resolveNotePresentation(note.content, {
      explicitTitle: note.title,
      authorName: authorLine,
      linkedEntityName: entityName,
      t,
    });
    pageTitle = pres.title;
    description = pres.body.slice(0, 160) || pres.title;
  } catch {}

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
    twitterCard: "summary_large_image",
  });
  return {
    title: pageTitle,
    description,
    alternates: localeAlternates(canonical, locale),
    ...shareMeta,
  };
}

export default async function NoteDetailPage({ params }: Params) {
  const { id } = await params;
  if (!isNoteRef(id)) notFound();
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const cookieStore = await cookies();
  const hasSession = cookieStore.has("hgs_session");
  const cookie = cookieStore.toString();
  let note: NoteItem;
  try {
    note = await apiGet<NoteItem>(`/notes/${id}`, hasSession ? { Cookie: cookie } : undefined);
  } catch (error) {
    if (isApiNotFound(error) || isApiGone(error)) notFound();
    throw error;
  }

  const authorLine = note.display_name || `@${note.username}`;
  // 关联化合物的解析名(上限 8 个, 命名走 CAS 优先链); 失败退 HCID 标签。
  const chemicalNames = await Promise.all(
    note.chemical_ids.slice(0, 8).map(async (cid) => {
      try {
        const chem = await apiGet<Chemical>(`/chemicals/${cid}`);
        return { id: cid, name: resolveChemicalName(chem, t.common.hcidLabel, locale).title };
      } catch {
        return { id: cid, name: t.common.hcidLabel(cid) };
      }
    }),
  );
  const linkedEntityName = chemicalNames[0]?.name
    ?? (note.reaction_ids.length > 0 ? t.common.hridLabel(note.reaction_ids[0]) : null);

  const { title, body } = resolveNotePresentation(note.content, {
    explicitTitle: note.title,
    authorName: authorLine,
    linkedEntityName,
    t,
  });
  const hasLinkedEntities = note.chemical_ids.length > 0 || note.reaction_ids.length > 0;

  return (
    <PageFrame tier="reading" className="note-detail-page">
      <PageHead
        breadcrumb={[
          { label: t.chemical.home, href: withLocale("/", locale) },
          { label: authorLine, href: withLocale(`/user/${encodeURIComponent(note.username)}`, locale) },
        ]}
        title={title}
        meta={
          <div className="note-detail-meta">
            <Byline user={note} time={new Date(note.updated_at).toLocaleDateString(locale)} size={32} />
            {note.visibility === "public"
              ? <Tag tone="blue">{t.notes.visibilityPublic}</Tag>
              : <Tag icon={<IconLock />}>{t.notes.visibilityPrivate}</Tag>}
            {note.visibility === "public" && (
              <span className="note-detail-views">{t.notes.viewCount(note.view_count ?? 0)}</span>
            )}
          </div>
        }
        actions={(note.visibility === "public" || hasSession) ? (
          <div className="hg-head-row">
            {/* 公开笔记与化合物/反应页同构：分享 iconOnly sm（私有不出） */}
            {note.visibility === "public" && (
              <ShareButton title={title} iconOnly size="sm" ariaLabel={t.guide.share} />
            )}
            {hasSession && (
              <NoteOwnerActions noteId={note.id} noteSlug={note.slug} ownerUsername={note.username} excerpt={note.content.slice(0, 24)} />
            )}
          </div>
        ) : undefined}
      />

      <article className="note-detail">
        {/* 正文以阅读体排版，阅读宽度（reading 720） */}
        {body && <div className="note-detail-content">{body}</div>}

        {/* 关联实体放在正文后面：化合物/反应统一 HCID/HRID 徽标，
            化合物徽标后跟随解析名（≤8 命名走 CAS 优先链，溢出纯徽标） */}
        {hasLinkedEntities && (
          <Section id="linked-entities" title={t.notes.linkedEntitiesTitle} className="note-detail-links-section">
            <div className="entity-note-links">
              {chemicalNames.map(({ id: cid, name }) => (
                <Link key={`c-${cid}`} className="entity-note-link" href={withLocale(`/chemical/${cid}`, locale)}>
                  <EntityBadge kind="chemical" id={cid} size="sm" ariaLabel={t.common.hcidLabel(cid)} />
                  <span>{name}</span>
                </Link>
              ))}
              {note.chemical_ids.slice(chemicalNames.length).map((cid) => (
                <EntityBadge
                  key={`c-${cid}`}
                  kind="chemical"
                  id={cid}
                  size="sm"
                  href={withLocale(`/chemical/${cid}`, locale)}
                  ariaLabel={t.common.hcidLabel(cid)}
                />
              ))}
              {note.reaction_ids.map((rid) => (
                <EntityBadge
                  key={`r-${rid}`}
                  kind="reaction"
                  id={rid}
                  size="sm"
                  href={withLocale(`/reaction/${rid}`, locale)}
                  ariaLabel={t.common.hridLabel(rid)}
                />
              ))}
            </div>
          </Section>
        )}
      </article>
    </PageFrame>
  );
}
