"use client";

/**
 * FollowButton — 关注/收藏按钮（v1.7 Step 7 起内部改用 ui/Button 组件，接口不变）。
 *
 * 乐观更新：点击立即翻状态并同步计数；成功且为「关注/收藏」方向时出 Toast
 * （带「撤销」）；失败回滚并 toast 报错；401 回滚后跳登录页带 next=当前页。
 * variant/size 可覆盖（默认 primary；创建者卡片等场景传 tonal sm）。
 */
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { apiPost, apiDelete, ApiError } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button, type ButtonVariant, type ButtonSize } from "@/components/ui/Button";
import { IconStar } from "@/components/ui/icons";
import { useToast } from "@/components/ui/Toast";

export function FollowButton({ endpoint, initial, count = 0, disabled = false, showCount = true, label = "follow", idleText, activeText, activeHoverText, onChange, variant = "primary", activeVariant, size, iconOnly = false }: {
  endpoint: string;
  initial: boolean;
  count?: number;
  disabled?: boolean;
  showCount?: boolean;
  label?: "follow" | "favor";
  idleText?: string;
  activeText?: string;
  /** IX-6：「已关注」hover 时显示「取消关注」—— 渲染双文案，CSS 悬停切换 */
  activeHoverText?: string;
  onChange?: (following: boolean) => void;
  /** 默认 primary；rail 创建者卡片等场景传 tonal/sm */
  variant?: ButtonVariant;
  /** 激活态（已关注/已收藏）的变体（Step 10：公开主页「已关注」= secondary） */
  activeVariant?: ButtonVariant;
  size?: ButtonSize;
  /** 星标图标按钮（Step 10：搜索卡片 / 主页反应卡收藏）；aria-label 取当前文案 */
  iconOnly?: boolean;
}) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const toast = useToast();
  const [following, setFollowing] = useState(initial);
  const [followers, setFollowers] = useState(count);
  const [busy, setBusy] = useState(false);
  // Toast「撤销」回调在渲染时被闭包捕获 —— 用 ref 读当前值，避免过期 state
  // 把撤销错发成再一次关注。
  const followingRef = useRef(initial);
  followingRef.current = following;
  const busyRef = useRef(false);
  busyRef.current = busy;

  async function apply(next: boolean) {
    if (disabled || busyRef.current) return;
    setBusy(true);
    const prev = followingRef.current;
    const prevCount = followers;
    setFollowing(next);
    setFollowers((value) => Math.max(value + (next ? 1 : -1), 0));
    try {
      if (prev) await apiDelete(endpoint);
      else await apiPost(endpoint);
      onChange?.(next);
      if (next) {
        toast.success(label === "favor" ? t.follow.favorToast : t.follow.followToast, {
          action: { label: t.follow.undo, onClick: () => { void apply(false); } },
        });
      }
    } catch (err) {
      setFollowing(prev);
      setFollowers(prevCount);
      if (err instanceof ApiError && err.status === 401) {
        // next = 当前完整路径(已带 locale 前缀, 原样保留); login 路径本身补当前 locale
        const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        router.push(withLocale(`/login?next=${encodeURIComponent(next)}`, locale));
        return;
      }
      toast.error(label === "favor" ? t.follow.favorErr : t.follow.followErr);
    } finally {
      setBusy(false);
    }
  }

  const text = following
    ? activeText || (label === "favor" ? t.follow.favoring : t.follow.following)
    : idleText || (label === "favor" ? t.follow.favor : t.follow.follow);
  // Step 10：图标形态（星标收藏）—— aria-label 用当前文案，已收藏实心
  if (iconOnly) {
    return (
      <Button
        variant={variant}
        size={size}
        iconOnly
        aria-label={text}
        aria-pressed={following}
        loading={busy}
        disabled={disabled}
        className={following ? "hg-star-on" : undefined}
        onClick={() => void apply(!followingRef.current)}
      >
        <IconStar />
      </Button>
    );
  }
  // 已关注且给了 hover 文案：双文案 CSS 切换（IX-6 hover 显示「取消关注」）
  const hoverSwap = following && activeHoverText;
  const currentVariant = following && activeVariant ? activeVariant : variant;
  return (
    <Button variant={currentVariant} size={size} aria-pressed={following} loading={busy} disabled={disabled} onClick={() => void apply(!followingRef.current)}>
      <span className={hoverSwap ? "hg-hover-swap" : undefined}>
        <span className="when-idle">{text}</span>
        {hoverSwap && <span className="when-hover">{activeHoverText}</span>}
      </span>
      {showCount && <strong className="follow-count">{followers.toLocaleString(locale)}</strong>}
    </Button>
  );
}
