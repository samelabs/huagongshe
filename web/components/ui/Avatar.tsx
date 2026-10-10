"use client";

/**
 * Avatar — 头像（参考 §6）：24 / 32 / 40 / 80。
 * 有图片用图片；没有则显示首字，底色按用户 id 取模从 --avatar-1…5 选。
 */
export type AvatarSize = 24 | 32 | 40 | 80;

export function Avatar({ id, name, src, size = 32, className }: {
  /** 用户 id（决定底色）；无账号语境可传任意稳定整数 */
  id: number | string;
  name?: string | null;
  src?: string | null;
  size?: AvatarSize;
  className?: string;
}) {
  const colorIndex = (typeof id === "number" ? id : id.split("").reduce((a, c) => a + c.charCodeAt(0), 0)) % 5 + 1;
  const initial = (name ?? "").trim().charAt(0).toUpperCase() || "?";
  const cls = ["hg-avatar", `s${size}`, `c${colorIndex}`, className ?? ""].filter(Boolean).join(" ");
  if (src) {
    // 头像图来自本站用户数据，宽高由组件锁死
    // eslint-disable-next-line @next/next/no-img-element
    return <img className={cls} src={src} width={size} height={size} alt={name ?? ""} />;
  }
  return name ? <span className={cls} aria-label={name} role="img">{initial}</span> : <span className={cls} aria-hidden="true">{initial}</span>;
}
