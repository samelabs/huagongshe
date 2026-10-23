"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useAccount } from "@/components/shared/AccountContext";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Field";
import { IconSparkle } from "@/components/ui/icons";
import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

export type Skill = {
  id: number;
  slug: string;
  title: string;
  description: string;
  category: string | null;
  is_official?: boolean;
  has_scripts: boolean;
  file_count: number;
  size_bytes: number;
};

// 分类字典：运行时从 /api/skills/categories 拉取（后台管理的唯一来源）
export type Category = { name: string; abbr: string; color: string; sort_order: number };

function CategoryIcon({ cat, size = 28 }: { cat: Category | undefined; size?: number }) {
  return (
    <span
      className="cat-icon"
      style={{ width: size, height: size, backgroundColor: cat?.color || "var(--n-500)" }}
      aria-hidden="true"
    >
      {cat?.abbr || "SK"}
    </span>
  );
}

// 默认渲染进 DOM 的技能卡上限; 超出经「查看全部」展开。
const SKILL_PREVIEW = 24;

export function SkillsClient({
  skills,
  cats,
  skillsError,
}: {
  skills: Skill[];
  cats: Category[] | null;
  skillsError: boolean;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>(t.skills.allCategories);
  const [showAll, setShowAll] = useState(false);

  const catMap = useMemo(() => new Map((cats ?? []).map((c) => [c.name, c])), [cats]);

  const categories = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of skills) {
      const cat = s.category || t.skills.defaultCategory;
      map.set(cat, (map.get(cat) || 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => {
      const oa = catMap.get(a[0])?.sort_order ?? 99;
      const ob = catMap.get(b[0])?.sort_order ?? 99;
      return oa - ob;
    });
  }, [skills, catMap, t.skills.defaultCategory]);

  const filtered = useMemo(() => {
    return skills.filter((s) => {
      const matchCategory =
        activeCategory === t.skills.allCategories || (s.category || t.skills.defaultCategory) === activeCategory;
      const q = query.toLowerCase().trim();
      const matchQuery =
        !q ||
        s.slug.toLowerCase().includes(q) ||
        s.title.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        (s.category || "").toLowerCase().includes(q);
      return matchCategory && matchQuery;
    });
  }, [skills, query, activeCategory, t.skills.allCategories, t.skills.defaultCategory]);

  // 分组只消费可见前 SKILL_PREVIEW 条; 分类 chips 的计数仍用完整 skills。
  const visible = useMemo(
    () => (showAll ? filtered : filtered.slice(0, SKILL_PREVIEW)),
    [filtered, showAll],
  );

  const grouped = useMemo(() => {
    const map = new Map<string, Skill[]>();
    for (const s of visible) {
      const cat = s.category || t.skills.defaultCategory;
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(s);
    }
    return Array.from(map.entries()).sort((a, b) => {
      const oa = catMap.get(a[0])?.sort_order ?? 99;
      const ob = catMap.get(b[0])?.sort_order ?? 99;
      return oa - ob;
    });
  }, [visible, catMap, t.skills.defaultCategory]);

  return (
    <PageFrame className="skills-page">
      {/* 页头（版式件 default）：面包屑 + 标题；检索框紧随页头 */}
      <PageHead
        breadcrumb={[
          { label: t.chemical.home, href: withLocale("/", locale) },
          { label: t.skills.openLibrary },
        ]}
        title={t.skills.heroTitle}
      />
      <div className="skills-search-bar">
        <Input
          type="text"
          enterKeyHint="search"
          value={query}
          onChange={(e) => { setQuery(e.target.value); setShowAll(false); }}
          placeholder={t.skills.searchPlaceholder}
          aria-label={t.skills.searchPlaceholder}
        />
      </div>

      {/* Category nav - 仅当分类成功返回时展示；分类失败时仅隐藏本条，不整页报错 */}
      {cats && cats.length > 0 && (
        <nav className="skills-cats" aria-label={t.skills.categoriesLabel}>
          <Button
            variant={activeCategory === t.skills.allCategories ? "primary" : "ghost"}
            size="sm"
            className={`skills-cat ${activeCategory === t.skills.allCategories ? "active" : ""}`}
            onClick={() => { setActiveCategory(t.skills.allCategories); setShowAll(false); }}
          >
            {t.skills.allCategories} <span className="skills-cat-count">{skills.length}</span>
          </Button>
          {categories.map(([cat, count]) => (
            <Button
              key={cat}
              variant={activeCategory === cat ? "primary" : "ghost"}
              size="sm"
              className={`skills-cat ${activeCategory === cat ? "active" : ""}`}
              onClick={() => { setActiveCategory(cat); setShowAll(false); }}
            >
              {cat} <span className="skills-cat-count">{count}</span>
            </Button>
          ))}
        </nav>
      )}

      {/* Skills 列表区 */}
      <div className="skills-content">
        {skillsError ? (
          <p className="skills-empty">{t.skills.loadFailed}</p>
        ) : skills.length === 0 ? (
          <EmptyState icon={<IconSparkle />} title={t.skills.emptySkills} />
        ) : filtered.length === 0 ? (
          <EmptyState icon={<IconSparkle />} title={t.skills.noMatch} />
        ) : (
          <>
            <div className="skills-groups">
              {grouped.map(([cat, catSkills]) => (
                <section key={cat} className="skills-group">
                  <h2 className="skills-group-title">
                    <CategoryIcon cat={catMap.get(cat)} size={26} />
                    <span className="skills-group-name">{cat}</span>
                    <span className="skills-group-count">{catSkills.length}</span>
                  </h2>
                  <div className="skills-grid">
                    {catSkills.map((s) => (
                      <SkillCard key={s.id} skill={s} cat={catMap.get(s.category || t.skills.defaultCategory)} labels={t} />
                    ))}
                  </div>
                </section>
              ))}
            </div>
            {filtered.length > SKILL_PREVIEW && (
              <div className="skills-show-all">
                <Button variant="ghost" size="md" onClick={() => setShowAll(!showAll)}>
                  {showAll ? t.skills.collapseSkills : t.skills.showAllSkills(filtered.length)}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </PageFrame>
  );
}

function SkillCard({ skill, cat, labels }: { skill: Skill; cat: Category | undefined; labels: Dictionary }) {
  const { user } = useAccount();
  const router = useRouter();
  const locale = useLocale();
  return (
    <article className="skills-card">
      <div className="skills-card-accent" style={{ backgroundColor: cat?.color || "var(--n-500)" }} />
      <div className="skills-card-body">
        <div className="skills-card-head">
          <h3 className="skills-card-name">{skill.slug}</h3>
          {Boolean(skill.is_official) && (
            <span className="skills-card-license">{labels.skills.officialBadge}</span>
          )}
          {skill.has_scripts && (
            <span className="skills-card-license" title={labels.skills.hasScriptsHint}>
              {labels.skills.hasScriptsBadge}
            </span>
          )}
        </div>
        <p className="skills-card-desc">{skill.description || labels.skills.noDescription}</p>
        <div className="skills-card-stats">
          <span className="skills-stat">{labels.skills.fileCount(skill.file_count)}</span>
          <span className="skills-stat">{labels.skills.sizeBytes(skill.size_bytes)}</span>
        </div>
        <div className="skills-card-actions">
          <Button
            variant="secondary"
            size="sm"
            className="skills-btn skills-btn-download"
            href={`/api/skills/${skill.id}/archive`}
            download={`${skill.slug}.zip`}
            /* 下载是登录能力: 匿名点击引导登录, 回跳本页 */
            onClick={(event) => {
              if (!user) {
                event.preventDefault();
                router.push(withLocale(`/login?next=${encodeURIComponent(withLocale(`/skills`, locale))}`, locale));
              }
            }}
          >
            {labels.skills.download}
          </Button>
        </div>
      </div>
    </article>
  );
}
