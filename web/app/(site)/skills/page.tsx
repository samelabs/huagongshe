import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { apiGet } from "@/lib/api.server";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { localeAlternates } from "@/lib/alternates";
import { SkillsClient, type Skill, type Category } from "./SkillsClient";
import { buildShareMetadata } from "@/lib/shareMeta";

async function skillsCount(cookie: string | null): Promise<number | null> {
  try {
    const data = await apiGet<{ total: number }>(`/skills?scope=public&page=1&page_size=1`,
      cookie ? { cookie } : undefined);
    return typeof data.total === "number" ? data.total : null;
  } catch {
    return null;
  }
}

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  const cookie = (await headers()).get("cookie");
  const n = await skillsCount(cookie);
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
    twitterCard: "summary_large_image",
  });
  return {
    title: t.skills.openLibrary,
    description: t.skills.metaDesc(count),
    alternates: localeAlternates("/skills", locale),
    // 技能浏览是登录能力: 私有面不进索引
    robots: { index: false, follow: false },
    ...shareMeta,
  };
}

export const dynamic = "force-dynamic";

async function loadCategories(cookie: string): Promise<Category[] | null> {
  try {
    return await apiGet<Category[]>("/skills/categories", { cookie });
  } catch {
    return null;
  }
}

async function loadSkills(cookie: string): Promise<{ skills: Skill[]; error: boolean }> {
  try {
    const first = await apiGet<{ total: number; items: Skill[] }>(
      "/skills?scope=public&page=1&page_size=100", { cookie },
    );
    const all: Skill[] = [...first.items];
    const total = first.total;
    if (all.length < total) {
      const remainingPages = Math.ceil(total / 100);
      const pagePromises: Promise<{ items: Skill[] }>[] = [];
      for (let p = 2; p <= remainingPages; p++) {
        pagePromises.push(apiGet<{ items: Skill[] }>(`/skills?scope=public&page=${p}&page_size=100`, { cookie }));
      }
      const rest = await Promise.all(pagePromises);
      for (const r of rest) all.push(...r.items);
    }
    return { skills: all, error: false };
  } catch {
    return { skills: [], error: true };
  }
}

export default async function SkillsPage() {
  const t = await getRequestDictionary();
  // 技能浏览是登录能力(HTTP/MCP 同墙): 无会话直接引导登录, 不渲染列表
  const cookieStore = await cookies();
  if (!cookieStore.has("hgs_session")) redirect("/login?next=/skills");
  const cookie = cookieStore.toString();
  // 分类与技能列表并行请求；错误分开处理（分类失败只隐藏导航，不整页报错）
  const [cats, skillsResult, totalCount] = await Promise.all([
    loadCategories(cookie),
    loadSkills(cookie),
    skillsCount(cookie),
  ]);

  const skills = skillsResult.skills;
  const n = typeof totalCount === "number" ? totalCount : skills.length;
  const count = t.skills.countUnit(n);

  return (
    <>
      <SkillsClient skills={skills} cats={cats} skillsError={skillsResult.error} />
    </>
  );
}
