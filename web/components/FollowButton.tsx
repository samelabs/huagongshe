"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import t from "@/lib/i18n";

export function FollowButton({ endpoint, initial, count = 0, disabled = false, showCount = true, label = t.follow.follow, idleText, activeText, onChange }: {
  endpoint: string;
  initial: boolean;
  count?: number;
  disabled?: boolean;
  showCount?: boolean;
  label?: "关注" | "收藏";
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
      const response = await fetch(endpoint, { method: following ? "DELETE" : "POST" });
      if (response.status === 401) {
        const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
        router.push(`/login?next=${encodeURIComponent(next)}`);
        return;
      }
      if (response.ok) {
        const next = !following;
        setFollowing(next); setFollowers((value) => Math.max(value + (following ? -1 : 1), 0));
        onChange?.(next);
        router.refresh();
      }
    } finally {
      setBusy(false);
    }
  }
  const text = following ? activeText || (label === "收藏" ? t.follow.favoring : t.follow.following) : idleText || label;
  return <button type="button" className={`follow-button ${following ? "following" : ""}`} onClick={toggle} disabled={disabled || busy}><span>{text}</span>{showCount && <strong>{followers.toLocaleString("zh-CN")}</strong>}</button>;
}
