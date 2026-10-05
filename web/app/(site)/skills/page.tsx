import type { Metadata } from "next";
import { apiGet } from "@/lib/api";
import { getRequestDictionary } from "@/lib/serverI18n";
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

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  const n = await skillsCount();
  const count = t.skills.countUnit(n);
  return {
  title: t.skills.openLibrary,
  description: t.skills.metaDesc(count),
  alternates: { canonical: "https://huagongshe.com/skills" },
  robots: { index: true, follow: true },
  openGraph: {
    title: t.skills.metaOgTitle(t.brand.name),
    description: t.skills.metaOgDesc(count),
    url: "/skills",
    siteName: t.brand.name,
    locale: "zh_CN",
    type: "website",
  },
  };
}

export const dynamic = "force-dynamic";

async function loadSkills(): Promise<{ skills: Skill[]; cats: Category[] }> {
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
    return { skills: all, cats };
  } catch {
    return { skills: [], cats: [] };
  }
}

export default async function SkillsPage() {
  const { skills, cats } = await loadSkills();
  return <KdenseSkillsClient skills={skills} cats={cats} loadError={skills.length === 0} />;
}
