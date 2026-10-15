/**
 * shareMeta — 全站公开页统一分享与 SEO 元数据 helper（DESIGN_SYSTEM 规范）
 *
 * 统一输出完整 OpenGraph、Twitter Card，以及微信等平台识别的
 * <meta itemprop="name|description|image">。
 *
 * 规则：
 * - 化合物页：结构图优先。分享图为结构图本身（方形，白底居中留白，基于 /api/mol/{id}/png），
 *   og:image 与 itemprop image 都用它；twitter:card 用 summary。
 * - 反应页：og:image 用反应式图；itemprop image 用方形白底的反应式图。
 * - 其他页面：og:image 用 1200×630 的 og.png；itemprop image 用方形的 512 logo。
 * - alt 文案走五语言字典，不写死中文。
 */
import type { Metadata } from "next";
import { SITE_ORIGIN, ogLocaleTag, type Locale } from "./alternates";
import { withLocale } from "./localePath";

export type ShareImage = {
  url: string;
  width: number;
  height: number;
  alt: string;
};

export type ShareMetaParams = {
  title: string;
  description: string;
  path: string;
  locale: Locale;
  siteName: string;
  ogImage: ShareImage;
  itempropImage?: string;
  twitterCard?: "summary" | "summary_large_image";
};

export function buildShareMetadata({
  title,
  description,
  path,
  locale,
  siteName,
  ogImage,
  itempropImage,
  twitterCard = "summary_large_image",
}: ShareMetaParams): Pick<Metadata, "openGraph" | "twitter"> {
  const ogUrl = ogImage.url.startsWith("http") ? ogImage.url : `${SITE_ORIGIN}${ogImage.url}`;

  return {
    openGraph: {
      title,
      description,
      url: withLocale(path, locale),
      siteName,
      locale: ogLocaleTag(locale),
      type: "website",
      images: [
        {
          url: ogUrl,
          width: ogImage.width,
          height: ogImage.height,
          alt: ogImage.alt,
        },
      ],
    },
    twitter: {
      card: twitterCard,
      title,
      description,
      images: [ogUrl],
    },
  };
}
