"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function FollowButton({ endpoint, initial, count = 0, disabled = false, showCount = true, label = "关注" }: {
  endpoint: string; initial: boolean; count?: number; disabled?: boolean; showCount?: boolean; label?: "关注" | "收藏";
}) {
  const router = useRouter();
  const [following, setFollowing] = useState(initial);
  const [followers, setFollowers] = useState(count);
  const [busy, setBusy] = useState(false);
  async function toggle() {
    if (disabled || busy) return;
    setBusy(true);
    const response = await fetch(endpoint, { method: following ? "DELETE" : "POST" });
    if (response.status === 401) {
      const next = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      router.push(`/login?next=${encodeURIComponent(next)}`);
      return;
    }
    if (response.ok) {
      setFollowing(!following); setFollowers((value) => Math.max(value + (following ? -1 : 1), 0));
      router.refresh();
    }
    setBusy(false);
  }
  return <button type="button" className={`follow-button ${following ? "following" : ""}`} onClick={toggle} disabled={disabled || busy}><span>{following ? `已${label}` : label}</span>{showCount && <strong>{followers.toLocaleString("zh-CN")}</strong>}</button>;
}
