"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { EntityBadge } from "@/components/ui/EntityBadge";
import { Tabs } from "@/components/ui/Tabs";
import { useToast } from "@/components/ui/Toast";
import { GlyphChem, GlyphRx, IconStar } from "@/components/ui/icons";
import { apiDelete, apiGet, apiPost, molSvgUrl } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { resolveChemicalName } from "@/lib/chemicalName";
import { useWorkbenchCounts } from "../WorkbenchCountsContext";
import { PanelError, PanelHeading, PanelLoading, Pagination, ReactionRow, WbListRow } from "../shared";
import type { ChemicalFollow, LoadState, PageResponse, PanelProps, Reaction, SavedKind } from "../types";

const emptyPage = <T,>(): PageResponse<T> => ({ items: [], total: 0, page: 1, page_size: 40 });

export function SavedPanel({ kind, page, initialChemicals, initialReactions }: PanelProps & {
  kind: SavedKind;
  initialChemicals?: PageResponse<ChemicalFollow> | null;
  initialReactions?: PageResponse<Reaction> | null;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const { counts, refresh: refreshCounts } = useWorkbenchCounts();
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

  /** §6 Step 9：Tabs 分 化合物/反应（带计数），切换走 URL 参数（SSR 预取一致） */
  function switchKind(next: string) {
    if (next === kind) return;
    router.push(withLocale(next === "reactions" ? "/aichem?tab=saved&kind=reactions" : "/aichem?tab=saved", locale));
  }

  /** IX-6：取消收藏即时生效（乐观移除），Toast 带「撤销」；失败回滚 + err Toast。
   * 撤销 = 重新 POST follow 并把行放回原位。 */
  function unfollowChemical(item: ChemicalFollow) {
    setChemicals((current) => ({
      ...current,
      items: current.items.filter((row) => row.id !== item.id),
      total: Math.max(current.total - 1, 0),
    }));
    apiDelete(`/chemicals/${item.id}/follow`)
      .then(() => {
        refreshCounts();
        toast.success(t.follow.unfavorToast, {
          action: {
            label: t.follow.undo,
            onClick: () => {
              apiPost(`/chemicals/${item.id}/follow`)
                .then(() => {
                  refreshCounts();
                  setChemicals((current) =>
                    current.items.some((row) => row.id === item.id)
                      ? current
                      : { ...current, items: [item, ...current.items], total: current.total + 1 });
                })
                .catch(() => toast.error(t.follow.favorErr));
            },
          },
        });
      })
      .catch(() => {
        setChemicals((current) =>
          current.items.some((row) => row.id === item.id)
            ? current
            : { ...current, items: [item, ...current.items], total: current.total + 1 });
        toast.error(t.follow.favorErr);
      });
  }

  function unfollowReaction(id: number) {
    setSavedReactions((current) => ({
      ...current,
      items: current.items.filter((row) => row.id !== id),
      total: Math.max(current.total - 1, 0),
    }));
    apiDelete(`/reactions/${id}/follow`)
      .then(() => {
        refreshCounts();
        toast.success(t.follow.unfavorToast, {
          action: {
            label: t.follow.undo,
            onClick: () => {
              apiPost(`/reactions/${id}/follow`)
                .then(() => {
                  refreshCounts();
                  apiGet<PageResponse<Reaction>>(`/users/me/follows/reactions?page=1&page_size=20`)
                    .then((value) => setSavedReactions(value))
                    .catch(() => toast.error(t.follow.favorErr));
                })
                .catch(() => toast.error(t.follow.favorErr));
            },
          },
        });
      })
      .catch(() => {
        apiGet<PageResponse<Reaction>>(`/users/me/follows/reactions?page=1&page_size=20`)
          .then((value) => setSavedReactions(value))
          .catch(() => {});
        toast.error(t.follow.favorErr);
      });
  }

  const data = kind === "chemicals" ? chemicals : savedReactions;
  /** Tabs 计数：dashboard 的收藏计数（侧栏徽标同一来源），未就绪时不显示数字 */
  const tabs = [
    { id: "chemicals", label: t.search.chemicalResults, count: counts?.chemicals },
    { id: "reactions", label: t.search.reactionResults, count: counts?.reactions },
  ];

  return (
    <section className="wb-panel">
      <PanelHeading title={t.me.tabSaved} subtitle={t.me.savedHint} count={state === "ready" ? data.total : "—"} unit={kind === "chemicals" ? t.me.unitChemical : t.me.unitReaction} />
      <Tabs tabs={tabs} value={kind} onChange={switchKind} ariaLabel={t.me.filterSaved} />
      {state === "loading" && <PanelLoading variant="list" />}
      {state === "error" && <PanelError error={error} />}
      {state === "ready" && kind === "chemicals" && (chemicals.items.length
        ? <div className="wb-row-list">
            {chemicals.items.map((item) => {
              const { title } = resolveChemicalName(item, t.common.hcidLabel, locale);
              return (
                <WbListRow
                  key={item.id}
                  href={`/chemical/${item.id}`}
                  thumb={
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={molSvgUrl(item.id, 96, 72)} height={44} alt="" loading="lazy" />
                  }
                  title={title}
                  meta={
                    <>
                      <EntityBadge kind="chemical" id={item.id} size="xs" ariaLabel={t.common.hcidLabel(item.id)} />
                      {item.molecular_formula && <span>{item.molecular_formula}</span>}
                    </>
                  }
                  side={
                    <>
                      {item.created_at && <time dateTime={item.created_at}>{t.me.savedAt(new Date(item.created_at).toLocaleDateString(locale))}</time>}
                      <span className="wb-row-actions">
                      <Button
                        variant="ghost"
                        iconOnly
                        className="wb-unfavor"
                        aria-label={t.follow.unfavorLabel}
                        onClick={() => unfollowChemical(item)}
                      >
                        <IconStar />
                      </Button>
                      </span>
                    </>
                  }
                />
              );
            })}
          </div>
        : <EmptyState icon={<GlyphChem />} title={t.me.emptyChemicals} action={{ label: t.me.tabSearch, href: withLocale("/aichem?tab=search", locale) }} />)}
      {state === "ready" && kind === "reactions" && (savedReactions.items.length
        ? <div className="wb-row-list">
            {savedReactions.items.map((item) => (
              <ReactionRow
                key={item.id}
                item={item}
                t={t}
                locale={locale}
                actions={
                  <Button
                    variant="ghost"
                    iconOnly
                    className="wb-unfavor"
                    aria-label={t.follow.unfavorLabel}
                    onClick={() => unfollowReaction(item.id)}
                  >
                    <IconStar />
                  </Button>
                }
              />
            ))}
          </div>
        : <EmptyState icon={<GlyphRx />} title={t.me.emptyReactionSaved} action={{ label: t.me.tabSearch, href: withLocale("/aichem?tab=search", locale) }} />)}
      {state === "ready" && data.total > data.page_size && (
        <Pagination page={page} pageSize={data.page_size} total={data.total} href={(value) => withLocale(`/aichem?tab=saved${kind === "reactions" ? "&kind=reactions" : ""}&page=${value}`, locale)} />
      )}
    </section>
  );
}
