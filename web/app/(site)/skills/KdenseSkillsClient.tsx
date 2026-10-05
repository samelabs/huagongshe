"use client";

import { useState, useMemo } from "react";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import type { Dictionary } from "@/lib/i18n/locales/zh-CN";

type Skill = {
  id: number;
  slug: string;
  title: string;
  description: string;
  category: string | null;
  origin: string;
  has_scripts: boolean;
  file_count: number;
  size_bytes: number;
};

// 分类字典：运行时从 /api/skills/categories 拉取（后台管理的唯一来源）
type Category = { name: string; abbr: string; color: string; sort_order: number };

function CategoryIcon({ cat, size = 28 }: { cat: Category | undefined; size?: number }) {
  return (
    <span
      className="cat-icon"
      style={{ width: size, height: size, backgroundColor: cat?.color || "#636e72" }}
      aria-hidden="true"
    >
      {cat?.abbr || "SK"}
    </span>
  );
}

export function KdenseSkillsClient({ skills, cats, loadError }: {
  skills: Skill[];
  cats: Category[];
  loadError: boolean;
}) {
  const t = useDictionary();
  const locale = useLocale();
  const error = loadError;
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>(t.skills.allCategories);


  const catMap = useMemo(() => new Map(cats.map((c) => [c.name, c])), [cats]);

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
  }, [skills, catMap]);

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
  }, [skills, query, activeCategory]);

  const grouped = useMemo(() => {
    const map = new Map<string, Skill[]>();
    for (const s of filtered) {
      const cat = s.category || t.skills.defaultCategory;
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(s);
    }
    return Array.from(map.entries()).sort((a, b) => {
      const oa = catMap.get(a[0])?.sort_order ?? 99;
      const ob = catMap.get(b[0])?.sort_order ?? 99;
      return oa - ob;
    });
  }, [filtered, catMap]);

  return (
    <div className="kdense-page">
      {/* Hero */}
      <section className="kdense-hero">
        <div className="kdense-hero-inner">
          <p className="kdense-breadcrumb">
            <a href={withLocale("/", locale)}>{t.brand.name}</a>
            <span className="kdense-sep">/</span>
            <span>{t.skills.openLibrary}</span>
          </p>
          <h1>{t.skills.heroTitle}</h1>
          <p className="kdense-subtitle">
            {t.skills.heroSubtitle(skills.length)}
          </p>
          <p className="kdense-source">
            {t.skills.heroSource}
          </p>
          <div className="kdense-search-bar">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t.skills.searchPlaceholder}
              aria-label={t.skills.searchPlaceholder}
            />
          </div>
        </div>
      </section>

      {/* Category nav */}
      <nav className="kdense-cats" aria-label={t.skills.categoriesLabel}>
        <button
          className={`kdense-cat ${activeCategory === t.skills.allCategories ? "active" : ""}`}
          onClick={() => setActiveCategory(t.skills.allCategories)}
        >
          {t.skills.allCategories} <span className="kdense-cat-count">{skills.length}</span>
        </button>
        {categories.map(([cat, count]) => (
          <button
            key={cat}
            className={`kdense-cat ${activeCategory === cat ? "active" : ""}`}
            onClick={() => setActiveCategory(cat)}
          >
            {cat} <span className="kdense-cat-count">{count}</span>
          </button>
        ))}
      </nav>

      {/* Skills */}
      <div className="kdense-content">
        {error ? (
          <p className="kdense-empty">{t.skills.loadFailed}</p>
        ) : filtered.length === 0 ? (
          <p className="kdense-empty">{t.skills.noMatch}</p>
        ) : (
          <div className="kdense-groups">
            {grouped.map(([cat, catSkills]) => (
              <section key={cat} className="kdense-group">
                <h2 className="kdense-group-title">
                  <CategoryIcon cat={catMap.get(cat)} size={26} />
                  <span className="kdense-group-name">{cat}</span>
                  <span className="kdense-group-count">{catSkills.length}</span>
                </h2>
                <div className="kdense-grid">
                  {catSkills.map((s) => (
                    <SkillCard key={s.id} skill={s} cat={catMap.get(s.category || t.skills.defaultCategory)} labels={t} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SkillCard({ skill, cat, labels }: { skill: Skill; cat: Category | undefined; labels: Dictionary }) {
  return (
    <article className="kdense-card">
      <div className="kdense-card-accent" style={{ backgroundColor: cat?.color || "#636e72" }} />
      <div className="kdense-card-body">
        <div className="kdense-card-head">
          <h3 className="kdense-card-name">{skill.slug}</h3>
          {skill.origin === "official" && (
            <span className="kdense-card-license">{labels.skills.officialBadge}</span>
          )}
          {skill.has_scripts && (
            <span className="kdense-card-license" title={labels.skills.hasScriptsHint}>
              {labels.skills.hasScriptsBadge}
            </span>
          )}
        </div>
        <p className="kdense-card-desc">{skill.description || labels.skills.noDescription}</p>
        <div className="kdense-card-stats">
          <span className="kdense-stat">{labels.skills.fileCount(skill.file_count)}</span>
          <span className="kdense-stat">{labels.skills.sizeBytes(skill.size_bytes)}</span>
        </div>
        <div className="kdense-card-actions">
          <a
            className="kdense-btn kdense-btn-download"
            href={`/api/skills/${skill.id}/archive`}
            download={`${skill.slug}.zip`}
          >
            {labels.skills.download}
          </a>
        </div>
      </div>
    </article>
  );
}
