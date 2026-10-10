import { ImageResponse } from "next/og";

import { OgBrandCard } from "@/components/OgBrandCard";
import { apiGet, isApiNotFound, type Chemical } from "@/lib/api";
import { resolveChemicalName } from "@/lib/chemicalName";
import { fetchMolPngDataUrl, logoDataUrl } from "@/lib/ogAssets";
import t from "@/lib/i18n";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";

/**
 * 化合物详情 OG 品牌卡（G4 收口）—— 1200×630：
 * HGS 标志 + 名称 + HCID 徽标 + 结构图（现有 /api/mol/{id}/png，不新增 API）。
 * 取数失败/404（爬虫打已删除页等）退化为无图兜底卡，不让 og 路由 500。
 * og:image / twitter:image 的 meta 由本文件路由自动产出。
 * 不用 generateImageMetadata（会被当 build-time 静态参数，禁 headers()）；
 * 卡片文字走请求时 getRequestDictionary —— og:image URL 不带 locale 前缀
 * （proxy 已排除元数据图片路由），按站点默认 locale 渲染。
 */
export const runtime = "nodejs";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = `${t.brand.name} · 化合物品牌卡`;

export default async function Image({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const locale = await getRequestLocale();
  const dict = await getRequestDictionary();
  const numericId = Number(id);

  const chemical = await apiGet<Chemical>(`/chemicals/${id}?enrich=core`).catch((error) => {
    if (isApiNotFound(error)) return null;
    throw error;
  });
  const { title } = chemical
    ? resolveChemicalName({ ...chemical, id }, dict.common.hcidLabel, locale)
    : { title: dict.common.hcidShort(id) };
  const structure = Number.isFinite(numericId) && chemical ? await fetchMolPngDataUrl(numericId) : null;
  const logo = await logoDataUrl();

  return new ImageResponse(
    (
      <OgBrandCard
        title={title}
        badge={dict.common.hcidShort(id)}
        note={dict.brand.seoDescShort}
        imageUrl={structure}
        logoSrc={logo}
        wordmark={dict.brand.name}
      />
    ),
    size,
  );
}

