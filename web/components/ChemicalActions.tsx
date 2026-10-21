"use client";

/**
 * ChemicalActions — 化合物详情头部的互动件。
 *
 * ChemicalActions（互动行组）：收藏（tonal 浅色 + 计数）——乐观更新，点击
 * 立即翻状态并出 Toast（带「撤销」），请求失败回滚并 toast 报错；401
 * 回滚后跳登录页带回跳地址。
 * ChemicalStructureLinks（结构图卡片按钮行）：子结构检索 / 相似结构
 * （secondary），所有宽度直接显示；未登录也显示，点击去登录页
 * （next=本页）。
 *
 * 端点与旧 FollowButton/搜索链接相同（/chemicals/{id}/follow、/search?mode=…），
 * 只重组展示，不改数据获取。
 */
import { useState } from "react";
import { useRouter } from "next/navigation";
import { apiPost, apiDelete, ApiError } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { useToast } from "@/components/ui/Toast";
import { IconStar, IconSearch, IconPlus } from "@/components/ui/icons";

export function ChemicalActions({ chemicalId, initialFollowing, initialCount }: {
  chemicalId: number;
  initialFollowing: boolean;
  initialCount: number;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const toast = useToast();
  const [following, setFollowing] = useState(initialFollowing);
  const [count, setCount] = useState(initialCount);
  const [busy, setBusy] = useState(false);

  const selfHref = withLocale(`/chemical/${chemicalId}`, locale);
  const loginHref = withLocale(`/login?next=${encodeURIComponent(selfHref)}`, locale);

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

  // 新建入口常显(未登录由 /aichem 与 /submit 的服务端登录门带回跳):
  // 笔记落工作台编辑并预填本化合物; 反应落提交页。
  return (
    <div className="chem-actions">
      <Button
        variant="ghost"
        size="sm"
        aria-pressed={following}
        loading={busy}
        onClick={() => void setFavor(!following)}
        className="chem-favor-btn"
      >
        <IconStar />
        <span>{following ? t.follow.favoring : t.follow.favor}</span>
      </Button>
      <Button variant="ghost" size="sm" href={withLocale(`/aichem?tab=notes&chemical=${chemicalId}&new=1`, locale)}>
        <IconPlus />
        {t.user.tabNotes}
      </Button>
      <Button variant="ghost" size="sm" href={withLocale("/submit", locale)}>
        <IconPlus />
        {t.user.tabReactions}
      </Button>
    </div>
  );
}

/** 结构图卡片下方的检索入口：子结构 / 相似结构；无结构（SMILES）时不渲染 */
export function ChemicalStructureLinks({ chemicalId, smiles, authed }: {
  chemicalId: number;
  smiles: string | null;
  /** 服务端 cookie 判定；未登录时检索按钮点击去登录 */
  authed: boolean;
}) {
  const t = useDictionary();
  const locale = useLocale();
  if (!smiles) return null;
  const selfHref = withLocale(`/chemical/${chemicalId}`, locale);
  const loginHref = withLocale(`/login?next=${encodeURIComponent(selfHref)}`, locale);
  const searchHref = (mode: "substructure" | "similarity") =>
    withLocale(`/search?q=${encodeURIComponent(smiles)}&mode=${mode}`, locale);
  const structureHref = (mode: "substructure" | "similarity") => (authed ? searchHref(mode) : loginHref);

  return (
    <div className="chem-struct-links">
      <Button variant="secondary" size="sm" href={structureHref("substructure")}>
        <IconSearch />
        {t.chemical.substructure}
      </Button>
      <Button variant="secondary" size="sm" href={structureHref("similarity")}>
        <IconSearch />
        {t.chemical.similarity}
      </Button>
    </div>
  );
}
