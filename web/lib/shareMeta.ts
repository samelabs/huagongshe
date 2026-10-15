/**
 * shareMeta — 全站公开页统一分享元数据 helper（DESIGN_SYSTEM 规范）
 *
 * 只输出一套标准协议：OpenGraph + Twitter Card。
 * - 化合物页：og:image 用 1:1 结构图（/img/chemical/{id}.png），twitter:card 用 summary。
 * - 反应页与其余页面：og:image 用横版图（/img/reaction/{id}.png 或 /og.png，
 *   1200×630），twitter:card 用 summary_large_image。
 * - og:image 一律写绝对地址，width/height 与实际图片一致。
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
  twitterCard?: "summary" | "summary_large_image";
};

export function buildShareMetadata({
  title,
  description,
  path,
  locale,
  siteName,
  ogImage,
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
