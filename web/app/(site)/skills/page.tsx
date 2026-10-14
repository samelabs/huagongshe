import type { Metadata } from "next";
import { apiGet } from "@/lib/api";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeAlternates, ogLocaleTag } from "@/lib/alternates";
import { withLocale } from "@/lib/localePath";
import { KdenseSkillsClient } from "./KdenseSkillsClient";

type Skill = {
  id: number; slug: string; title: string; description: string;
  category: string | null; origin: string; has_scripts: boolean;
  file_count: number; size_bytes: number;
};
type Category = { name: string; abbr: string; color: string; sort_order: number };

// 0904 ⑰: 技能计数动态化 — 原硬编码"159 个"会随库变化失实。
// generateMetadata 每次构建/请求取 real total; 失败降级为不带数字的描述。
async function skillsCount(): Promise<number | null> {
  try {
    const data = await apiGet<{ total: number }>(`/skills?scope=public&page=1&page_size=1`);
    return typeof data.total === "number" ? data.total : null;
  } catch {
    return null;
  }
}

import { buildShareMetadata } from "@/lib/shareMeta";
import { WeChatMeta } from "@/components/shared/WeChatMeta";

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const n = await skillsCount();
  const count = t.skills.countUnit(n);
  const shareMeta = buildShareMetadata({
    title: t.skills.metaOgTitle(t.brand.name),
    description: t.skills.metaOgDesc(count),
    path: "/skills",
    locale,
    siteName: t.brand.name,
    ogImage: {
      url: "/og.png",
      width: 1200,
      height: 630,
      alt: t.brand.ogAlt,
    },
    itempropImage: "/icon-512.png",
    twitterCard: "summary_large_image",
  });
  return {
    title: t.skills.openLibrary,
    description: t.skills.metaDesc(count),
    alternates: localeAlternates("/skills", locale),
    robots: { index: true, follow: true },
    ...shareMeta,
  };
}

export const dynamic = "force-dynamic";

async function loadSkills(): Promise<{ skills: Skill[]; cats: Category[]; error: boolean }> {
  // SSR(loopback=内部通道)拉全量公开池; 失败降级为空集+错误标记
  try {
    const cats = await apiGet<Category[]>("/skills/categories");
    const all: Skill[] = [];
    for (let page = 1; ; page += 1) {
      const data = await apiGet<{ total: number; items: Skill[] }>(
        `/skills?scope=public&page=${page}&page_size=100`,
      );
      all.push(...data.items);
      if (all.length >= data.total || data.items.length === 0) break;
    }
    return { skills: all, cats, error: false };
  } catch {
    return { skills: [], cats: [], error: true };
  }
}

export default async function SkillsPage() {
  const t = await getRequestDictionary();
  const { skills, cats, error } = await loadSkills();
  const n = skills.length;
  const count = t.skills.countUnit(n);
  return (
    <>
      <WeChatMeta name={t.skills.metaOgTitle(t.brand.name)} description={t.skills.metaOgDesc(count)} image="/icon-512.png" />
      <KdenseSkillsClient skills={skills} cats={cats} loadError={error} />
    </>
  );
}
