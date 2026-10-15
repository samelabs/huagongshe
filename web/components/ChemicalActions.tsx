"use client";

/**
 * ChemicalActions — 化合物详情头部操作行（DESIGN_SYSTEM 6.3）。
 *
 * 收藏（primary + 计数）：乐观更新——点击立即翻状态并出 Toast（带「撤销」），
 * 请求失败回滚并 toast 报错；401 回滚后跳登录页带回跳地址。
 * 子结构检索 / 相似结构（secondary）：未登录也显示，点击去登录页（next=本页）。
 * 分享（ghost icon）：navigator.share 退回复制链接 + Toast。
 *
 * 端点与旧 FollowButton/搜索链接相同（/chemicals/{id}/follow、/search?mode=…），
 * 只重组展示，不改数据获取。
 */
import { useState } from "react";
import { useDismissableMenu } from "@/lib/useDismissableMenu";
import { useRouter } from "next/navigation";
import { apiPost, apiDelete, ApiError } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { IconStar, IconSearch, IconMore } from "@/components/ui/icons";

export function ChemicalActions({ chemicalId, smiles, initialFollowing, initialCount, authed, title }: {
  chemicalId: number;
  smiles: string | null;
  initialFollowing: boolean;
  initialCount: number;
  /** 服务端 cookie 判定；未登录时结构检索按钮点击去登录 */
  authed: boolean;
  title: string;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const [following, setFollowing] = useState(initialFollowing);
  const [count, setCount] = useState(initialCount);
  const [busy, setBusy] = useState(false);
  const menu = useDismissableMenu();
  const { open: menuOpen, setOpen: setMenuOpen } = menu;

  const selfHref = withLocale(`/chemical/${chemicalId}`, locale);
  const loginHref = withLocale(`/login?next=${encodeURIComponent(selfHref)}`, locale);
  const searchHref = (mode: "substructure" | "similarity") =>
    withLocale(`/search?q=${encodeURIComponent(smiles ?? "")}&mode=${mode}`, locale);
  const structureHref = (mode: "substructure" | "similarity") => (authed ? searchHref(mode) : loginHref);

  async function setFavor(next: boolean) {
    if (busy) return;
    setBusy(true);
    const prevFollowing = following;
    const prevCount = count;
    setFollowing(next);
    setCount(Math.max(0, count + (next ? 1 : -1)));
    try {
      if (next) await apiPost(`/chemicals/${chemicalId}/follow`);
      else await apiDelete(`/chemicals/${chemicalId}/follow`);
      if (next) {
        toast.success(t.follow.favorToast, {
          action: { label: t.follow.undo, onClick: () => { void setFavor(false); } },
        });
      }
    } catch (err) {
      setFollowing(prevFollowing);
      setCount(prevCount);
      if (err instanceof ApiError && err.status === 401) {
        router.push(loginHref);
        return;
      }
      toast.error(t.follow.favorErr);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chem-head-actions">
      <Button
        variant="primary"
        aria-pressed={following}
        loading={busy}
        onClick={() => void setFavor(!following)}
        className="chem-favor-btn"
      >
        <IconStar />
        <span>{following ? t.follow.favoring : t.follow.favor}</span>
        <strong className="chem-favor-count">{count.toLocaleString(locale)}</strong>
      </Button>
      {smiles && (
        <Button variant="secondary" href={structureHref("substructure")} className="chem-substruct-btn">
          <IconSearch />
          {t.chemical.substructure}
        </Button>
      )}

      {/* 桌面端（>640px）：平铺展示全部操作（DESIGN_SYSTEM 6.3） */}
      <div className="chem-actions-desktop">
        {smiles && (
          <Button variant="secondary" className="chem-similarity-btn" href={structureHref("similarity")}>
            <IconSearch />
            {t.chemical.similarity}
          </Button>
        )}
      </div>

      {/* 手机端（≤640px）：更多菜单（DESIGN_SYSTEM 5.5 / IX-11） */}
      {smiles && (
        <div className="chem-actions-more hg-menu-wrap" ref={menu.rootRef} onKeyDown={menu.onKeyDown}>
          <Button
            variant="secondary"
            iconOnly
            aria-label={t.nav.more}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="chem-more-btn"
            ref={menu.triggerRef}
          >
            <IconMore />
          </Button>
          {menuOpen && (
            <div className="hg-menu-panel" role="menu">
              <Button
                variant="ghost"
                href={structureHref("similarity")}
                onClick={() => setMenuOpen(false)}
                role="menuitem"
                data-menu-item
              >
                <IconSearch />
                {t.chemical.similarity}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
