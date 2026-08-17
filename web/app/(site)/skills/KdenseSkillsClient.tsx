"use client";

import { useState, useMemo, useEffect } from "react";
import { apiGet } from "@/lib/api";

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
      style={{
        width: size,
        height: size,
        backgroundColor: cat?.color || "#636e72",
        fontSize: size * 0.36,
      }}
      aria-hidden="true"
    >
      {cat?.abbr || "SK"}
    </span>
  );
}

export function KdenseSkillsClient() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [cats, setCats] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("全部");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const catData = await apiGet<Category[]>(`/skills/categories`);
        if (!active) return;
        setCats(catData);
        const all: Skill[] = [];
        let page = 1;
        for (;;) {
          const data = await apiGet<{ total: number; items: Skill[] }>(
            `/skills?scope=public&page=${page}&page_size=100`
          );
          if (!active) return;
          all.push(...data.items);
          if (all.length >= data.total || data.items.length === 0) break;
          page += 1;
        }
        if (!active) return;
        setSkills(all);
        setLoading(false);
      } catch {
        if (active) {
          setError(true);
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  const catMap = useMemo(() => new Map(cats.map((c) => [c.name, c])), [cats]);

  const categories = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of skills) {
      const cat = s.category || "通用工具";
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
        activeCategory === "全部" || (s.category || "通用工具") === activeCategory;
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
      const cat = s.category || "通用工具";
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
            <a href="/">化工社</a>
            <span className="kdense-sep">/</span>
            <span>开放技能库</span>
          </p>
          <h1>科学 AI 开放技能库</h1>
          <p className="kdense-subtitle">
            {skills.length} 个开源科学 AI Agent 技能 —— 覆盖化学、生物、机器学习、科研写作等领域，可按需下载使用。
          </p>
          <p className="kdense-source">
            数据来源：K-Dense-AI/scientific-agent-skills (MIT) 与化工社官方技能 · 由化工社整理提供
          </p>
          <div className="kdense-search-bar">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索技能名称或关键词…"
              aria-label="搜索技能"
            />
          </div>
        </div>
      </section>

      {/* Category nav */}
      <nav className="kdense-cats" aria-label="技能分类">
        <button
          className={`kdense-cat ${activeCategory === "全部" ? "active" : ""}`}
          onClick={() => setActiveCategory("全部")}
        >
          全部 <span className="kdense-cat-count">{skills.length}</span>
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
        {loading ? (
          <p className="kdense-loading">加载中…</p>
        ) : error ? (
          <p className="kdense-empty">数据读取失败，请刷新后重试。</p>
        ) : filtered.length === 0 ? (
          <p className="kdense-empty">未找到匹配的技能</p>
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
                    <SkillCard key={s.id} skill={s} cat={catMap.get(s.category || "通用工具")} />
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

function SkillCard({ skill, cat }: { skill: Skill; cat: Category | undefined }) {
  const [expanded, setExpanded] = useState(false);
  const color = cat?.color || "#636e72";

  return (
    <article className={`kdense-card ${expanded ? "expanded" : ""}`}>
      <div className="kdense-card-accent" style={{ backgroundColor: color }} />
      <div className="kdense-card-body">
        <div className="kdense-card-head">
          <h3 className="kdense-card-name">{skill.slug}</h3>
          {skill.origin === "official" && (
            <span className="kdense-card-license">官方</span>
          )}
          {skill.has_scripts && (
            <span className="kdense-card-license" title="该技能包含脚本文件，使用前请人工审阅">
              含脚本
            </span>
          )}
        </div>
        <p className="kdense-card-desc">{skill.description || "暂无描述"}</p>
        <div className="kdense-card-stats">
          <span className="kdense-stat">{skill.file_count} 文件</span>
        </div>
        {expanded && (
          <div className="kdense-card-detail">
            <p>{skill.description}</p>
          </div>
        )}
        <div className="kdense-card-actions">
          <button
            className="kdense-btn kdense-btn-toggle"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "收起" : "详情"}
          </button>
          <a
            className="kdense-btn kdense-btn-download"
            href={`/api/skills/${skill.id}/archive`}
            download={`${skill.slug}.zip`}
          >
            下载技能包
          </a>
        </div>
      </div>
    </article>
  );
}
