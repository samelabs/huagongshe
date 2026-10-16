"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Avatar — 头像（DESIGN_SYSTEM 3.12）：24 / 32 / 40 / 80。
 * 有图片用图片；没有图片或图片加载失败时显示首字，底色按用户 id 取模从 --avatar-1…5 选。
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
  const [failed, setFailed] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  // 服务端渲染的图片可能在水合前就已加载失败，error 事件不会再触发：挂载时补查一次
  useEffect(() => {
    const img = imgRef.current;
    setFailed(Boolean(img && img.complete && img.naturalWidth === 0));
  }, [src]);

  const colorIndex = (typeof id === "number" ? id : id.split("").reduce((a, c) => a + c.charCodeAt(0), 0)) % 5 + 1;
  const initial = (name ?? "").trim().charAt(0).toUpperCase() || "?";
  const cls = ["hg-avatar", `s${size}`, `c${colorIndex}`, className ?? ""].filter(Boolean).join(" ");
  if (src && !failed) {
    // 头像图来自本站用户数据，宽高由组件锁死
    // eslint-disable-next-line @next/next/no-img-element
    return <img ref={imgRef} className={cls} src={src} width={size} height={size} alt={name ?? ""} onError={() => setFailed(true)} />;
  }
  return name ? <span className={cls} aria-label={name} role="img">{initial}</span> : <span className={cls} aria-hidden="true">{initial}</span>;
}
