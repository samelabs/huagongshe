import { SITE_ORIGIN } from "@/lib/alternates";

/**
 * WeChatMeta — 微信等平台识别的 itemprop meta 标签（React 19 自动提升到 <head>）
 */
export function WeChatMeta({
  name,
  description,
  image,
}: {
  name: string;
  description: string;
  image: string;
}) {
  const fullImage = image.startsWith("http") ? image : `${SITE_ORIGIN}${image}`;
  return (
    <>
      <meta itemProp="name" content={name} />
      <meta itemProp="description" content={description} />
      <meta itemProp="image" content={fullImage} />
    </>
  );
}
