"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { apiPost, apiDelete, ApiError } from "@/lib/api";
import t from "@/lib/i18n";
import { SITE_LOCALE } from "@/lib/locale";

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
        const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
        return;
      }
    } finally {
      setBusy(false);
    }
  }
  const text = following
    ? activeText || (label === "favor" ? t.follow.favoring : t.follow.following)
    : idleText || (label === "favor" ? t.follow.favor : t.follow.follow);
  return <button type="button" className={`follow-button ${following ? "following" : ""}`} onClick={toggle} disabled={disabled || busy}><span>{text}</span>{showCount && <strong>{followers.toLocaleString(SITE_LOCALE)}</strong>}</button>;
}
