import type { Metadata } from "next";
import { apiGet } from "@/lib/api";
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
  const n = await skillsCount();
  const count = n === null ? "" : `${n} 个`;
  return {
  title: "开放技能库",
  description:
    `${count}开源科学 AI Agent 技能 —— 覆盖化学、生物、机器学习、科研写作等领域。数据来自 K-Dense-AI/scientific-agent-skills 开源项目与化工社AIchem官方技能。`,
  alternates: { canonical: "https://huagongshe.com/skills" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "科学 AI 开放技能库｜化工社AIchem",
    description: `${count}开源科学 AI Agent 技能，覆盖化学、生物、机器学习等研究领域。`,
    url: "/skills",
    siteName: "化工社AIchem",
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
