import { ImageResponse } from "next/og";

import { OgBrandCard } from "@/components/OgBrandCard";
import { apiGet, type ReactionDetail } from "@/lib/api";
import { fetchMolPngDataUrl, logoDataUrl } from "@/lib/ogAssets";
import t from "@/lib/i18n";
import { getRequestDictionary } from "@/lib/serverI18n";

/**
 * 反应详情 OG 品牌卡（G4 收口）—— 1200×630：
 * HGS 标志 + HRID 徽标 + 结构图 = 第一个 PRODUCT 参与物的 /api/mol/{id}/png
 * （现有 API，不新增）。无 cookie 调用 → 私有/隐藏反应 404 → 无图兜底卡。
 * 不用 generateImageMetadata（会被当 build-time 静态参数，禁 headers()）；
 * 卡片文字走请求时 getRequestDictionary —— og:image URL 不带 locale 前缀
 * （proxy 已排除元数据图片路由），按站点默认 locale 渲染。
 */
export const runtime = "nodejs";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = `${t.brand.name} · 反应品牌卡`;

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const t = await getRequestDictionary();

  const reaction = await apiGet<ReactionDetail>(`/reactions/${id}`).catch(() => null);
  // 结构图选「纯 PRODUCT」参与物（副产物常同时挂 CATALYST/PRODUCT 双角色，
  // 种子 HRID 1 里乙酸即如此）—— 无纯 PRODUCT 再退回第一个 PRODUCT
  const products = reaction?.participants.filter((p) => p.role === "PRODUCT") ?? [];
  const exclusive = products.filter(
    (p) => !reaction!.participants.some((q) => q.id === p.id && q.role !== "PRODUCT"));
  const product = exclusive[0] ?? products[0];
  const structure = product ? await fetchMolPngDataUrl(product.id) : null;
  const logo = await logoDataUrl();

  return new ImageResponse(
    (
      <OgBrandCard
        title={t.reaction.detail}
        badge={t.common.hridShort(id)}
        note={t.reaction.desc}
        imageUrl={structure}
        logoSrc={logo}
        wordmark={t.brand.name}
      />
    ),
    size,
  );
}
