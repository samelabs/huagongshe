"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiPost, apiDelete, ApiError } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";

export function FollowButton({ endpoint, initial, count = 0, disabled = false, showCount = true, label = "follow", idleText, activeText, onChange }: {
  endpoint: string;
  initial: boolean;
  count?: number;
  disabled?: boolean;
  showCount?: boolean;
  label?: "follow" | "favor";
  idleText?: string;
  activeText?: string;
  onChange?: (following: boolean) => void;
}) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const [following, setFollowing] = useState(initial);
  const [followers, setFollowers] = useState(count);
  const [busy, setBusy] = useState(false);
  async function toggle() {
    if (disabled || busy) return;
    setBusy(true);
    try {
      if (following) {
        await apiDelete(endpoint);
      } else {
        await apiPost(endpoint);
      }
      const next = !following;
      setFollowing(next); setFollowers((value) => Math.max(value + (following ? -1 : 1), 0));
      onChange?.(next);
      router.refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        // next = 当前完整路径(已带 locale 前缀, 原样保留); login 路径本身补当前 locale
        const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        router.push(withLocale(`/login?next=${encodeURIComponent(next)}`, locale));
        return;
      }
    } finally {
      setBusy(false);
    }
  }
  const text = following
    ? activeText || (label === "favor" ? t.follow.favoring : t.follow.following)
    : idleText || (label === "favor" ? t.follow.favor : t.follow.follow);
  return <button type="button" className={`follow-button ${following ? "following" : ""}`} onClick={toggle} disabled={disabled || busy}><span>{text}</span>{showCount && <strong>{followers.toLocaleString(locale)}</strong>}</button>;
}
