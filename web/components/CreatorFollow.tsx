"use client";

/**
 * CreatorFollow — 反应页创建者卡片的关注按钮（Step 8 Part A）。
 *
 * - 已登录且非本人：用公开主页读接口 GET /users/{username}（含 is_following）
 *   取初始状态；请求完成前按钮 loading，不先显示「关注」。
 * - 未登录：显示「关注」，点击跳登录（next= 当前页，登录后回来）。
 * - 状态到手后交给 FollowButton（乐观更新 + Toast 撤销 + 失败回滚）。
 */
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiGet } from "@/lib/api";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { FollowButton } from "@/components/shared/FollowButton";

type PublicProfile = { is_following: boolean };

export function CreatorFollow({ username, loggedIn }: { username: string; loggedIn: boolean }) {
  const t = useDictionary();
  const locale = useLocale();
  const router = useRouter();
  const [state, setState] = useState<"loading" | "ready" | "failed">(loggedIn ? "loading" : "ready");
  const [initial, setInitial] = useState(false);

  useEffect(() => {
    if (!loggedIn) return;
    let active = true;
    // 公开主页读接口（/user/[username] 同源数据），返回 is_following
    apiGet<PublicProfile>(`/users/${encodeURIComponent(username)}`)
      .then((profile) => { if (active) { setInitial(profile.is_following); setState("ready"); } })
      .catch(() => { if (active) setState("failed"); });
    return () => { active = false; };
  }, [username, loggedIn]);

  if (loggedIn && state === "loading") {
    return (
      <Button variant="tonal" size="sm" loading disabled aria-live="polite">
        <span>{t.follow.follow}</span>
      </Button>
    );
  }
  if (!loggedIn) {
    return (
      <Button
        variant="tonal"
        size="sm"
        onClick={() => {
          const next = `${window.location.pathname}${window.location.search}`;
          router.push(withLocale(`/login?next=${encodeURIComponent(next)}`, locale));
        }}
      >
        <span>{t.follow.follow}</span>
      </Button>
    );
  }
  // failed：拿不到初始态时退回 false 初始（点击后以服务器结果为准）
  return (
    <FollowButton
      endpoint={`/users/${encodeURIComponent(username)}/follow`}
      initial={initial}
      showCount={false}
      variant="tonal"
      size="sm"
    />
  );
}
