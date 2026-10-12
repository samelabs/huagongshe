import { ImageResponse } from "next/og";

import { OgBrandCard } from "@/components/OgBrandCard";
import { logoDataUrl } from "@/lib/ogAssets";
import t from "@/lib/i18n";
import { notFound } from "next/navigation";
import { isEntityId } from "@/lib/api";
import { getRequestDictionary } from "@/lib/serverI18n";

/**
 * 笔记详情 OG 品牌卡（G4 收口）—— 1200×630，纯兜底构图：
 * HGS 标志 + 「笔记 {id}」+ 品牌一行。刻意不取笔记内容、不取所属实体
 * （沿用页面元数据既有隐私口径：私有笔记内容不得进入公开 metadata，
 * 笔记也没有自己的结构图可画）。
 * 不用 generateImageMetadata（会被当 build-time 静态参数，禁 headers()）；
 * 卡片文字走请求时 getRequestDictionary —— og:image URL 不带 locale 前缀
 * （proxy 已排除元数据图片路由），按站点默认 locale 渲染。
 */
export const runtime = "nodejs";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = `${t.brand.name} · 笔记品牌卡`;

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // FX-3（SMK-002）：非法 ID 与页面同一口径 → 404
  if (!isEntityId(id)) notFound();
  const t = await getRequestDictionary();
  const logo = await logoDataUrl();

  return new ImageResponse(
    (
      <OgBrandCard
        title={`${t.notes.detailTitle} ${id}`}
        badge={t.notes.detailTitle}
        note={t.brand.seoDescShort}
        imageUrl={null}
        logoSrc={logo}
        wordmark={t.brand.name}
      />
    ),
    size,
  );
}
