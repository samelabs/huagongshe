"use client";

/**
 * Byline — 署名（版式基准）：头像 + 显示名 + @用户名，整体链接到主页。
 * 账号停用时显示停用标记、不出链接；可附时间与私有标记。
 * 用户四字段（username/display_name/avatar_url/active）与接口投影同口径。
 */
import { forwardRef } from "react";
import Link from "next/link";

import { useDictionary } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { useLocale } from "@/components/shared/I18nContext";
import { Avatar } from "./Avatar";
import { Tag } from "./Tag";

export type BylineUser = {
  username: string;
  display_name: string | null;
  avatar_url?: string | null;
  active?: boolean;
};

export const Byline = forwardRef<HTMLDivElement, {
  user: BylineUser;
  /** 已格式化的时间文案（如“发布于 2026-10-01”），由调用方按 locale 组织 */
  time?: string;
  /** 私有标记（随数据出现，不在此组件判断） */
  privateMark?: boolean;
  size?: 24 | 32;
  className?: string;
}>(function Byline(
  { user, time, privateMark, size = 24, className },
  ref,
) {
  const t = useDictionary();
  const locale = useLocale();
  const name = user.display_name || user.username;
  const avatar = (
    <Avatar
      id={user.username}
      name={name}
      src={user.avatar_url || undefined}
      size={size}
    />
  );
  const identity = user.active === false ? (
    <span className="hg-byline-main">
      {avatar}
      <span className="hg-byline-name">{name}</span>
      <Tag tone="neutral" dot>{t.user.authorDeactivated}</Tag>
    </span>
  ) : (
    <Link
      className="hg-byline-link"
      href={withLocale(`/user/${encodeURIComponent(user.username)}`, locale)}
    >
      {avatar}
      <span className="hg-byline-name">{name}</span>
      <span className="hg-byline-handle">@{user.username}</span>
    </Link>
  );
  return (
    <div ref={ref} className={`hg-byline${className ? ` ${className}` : ""}`}>
      {identity}
      {time && <span className="hg-byline-time">{time}</span>}
      {privateMark && <Tag tone="warn">{t.common.private}</Tag>}
    </div>
  );
});
