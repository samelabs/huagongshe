"use client";

import { useState, useMemo, useEffect } from "react";

type Skill = {
  name: string;
  category: string;
  category_order: number;
  description: string;
  detail: string;
  license: string;
  file_count: number;
  ref_count: number;
  github_path: string;
};

const GITHUB_RAW_BASE =
  "https://raw.githubusercontent.com/K-Dense-AI/scientific-agent-skills/main";
const GITHUB_TREE_BASE =
  "https://github.com/K-Dense-AI/scientific-agent-skills/tree/main";

// 每个分类配一个简洁的缩写标签（2字母），用 CSS 渲染色块
const CATEGORY_TAGS: Record<string, string> = {
  化学信息学: "CH",
  生物信息学: "BI",
  临床与医学: "MD",
  "机器学习与AI": "AI",
  统计分析: "ST",
  科研写作与文献: "WR",
  科学可视化: "VZ",
  数据处理: "DA",
  平台集成: "PL",
  地球与物理科学: "PH",
  研究方法论: "RM",
  通用工具: "UT",
};

// 每个分类配一个色值（与化工社色系协调）
const CATEGORY_COLORS: Record<string, string> = {
  化学信息学: "#1e90ff",
  生物信息学: "#0f9d58",
  临床与医学: "#e84393",
  "机器学习与AI": "#6c5ce7",
  统计分析: "#fd7e14",
  科研写作与文献: "#00b894",
  科学可视化: "#e17055",
  数据处理: "#0984e3",
  平台集成: "#a29bfe",
  地球与物理科学: "#2d3436",
  研究方法论: "#d63031",
  通用工具: "#636e72",
};

function CategoryIcon({ category, size = 28 }: { category: string; size?: number }) {
  const tag = CATEGORY_TAGS[category] || "SK";
  const color = CATEGORY_COLORS[category] || "#636e72";
  return (
    <span
      className="cat-icon"
      style={{
        width: size,
        height: size,
        backgroundColor: color,
        fontSize: size * 0.36,
      }}
      aria-hidden="true"
    >
      {tag}
    </span>
  );
}

export function KdenseSkillsClient() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("全部");

  useEffect(() => {
    fetch("/kdense-skills.json")
      .then((r) => r.json())
      .then((data: Skill[]) => {
        setSkills(data);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  const categories = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of skills) {
      map.set(s.category, (map.get(s.category) || 0) + 1);
    }
    return Array.from(map.entries()).sort((a, b) => {
      const sa = skills.find((s) => s.category === a[0]);
      const sb = skills.find((s) => s.category === b[0]);
      return (sa?.category_order ?? 99) - (sb?.category_order ?? 99);
    });
  }, [skills]);

  const filtered = useMemo(() => {
    return skills.filter((s) => {
      const matchCategory =
        activeCategory === "全部" || s.category === activeCategory;
      const q = query.toLowerCase().trim();
      const matchQuery =
        !q ||
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.category.toLowerCase().includes(q);
      return matchCategory && matchQuery;
    });
  }, [skills, query, activeCategory]);

  const grouped = useMemo(() => {
    const map = new Map<string, Skill[]>();
    for (const s of filtered) {
      if (!map.has(s.category)) map.set(s.category, []);
      map.get(s.category)!.push(s);
    }
    return Array.from(map.entries()).sort((a, b) => {
      const sa = a[1][0];
      const sb = b[1][0];
      return (sa?.category_order ?? 99) - (sb?.category_order ?? 99);
    });
  }, [filtered]);

  return (
    <div className="kdense-page">
      {/* Hero */}
      <section className="kdense-hero">
        <div className="kdense-hero-inner">
          <p className="kdense-breadcrumb">
            <a href="/">化工社</a>
            <span className="kdense-sep">/</span>
            <span>Open Skills</span>
          </p>
          <h1>Scientific AI Skills Library</h1>
          <p className="kdense-subtitle">
            {skills.length || 158} open-source AI agent skills for scientific research — chemistry, biology, machine learning, academic writing &amp; more.
          </p>
          <p className="kdense-source">
            Source:{" "}
            <a href={GITHUB_TREE_BASE} target="_blank" rel="noopener noreferrer">
              K-Dense-AI/scientific-agent-skills
            </a>{" "}
            · MIT License · Curated by huagongshe.com
          </p>
          <div className="kdense-search-bar">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search skills by name or keyword…"
              aria-label="Search skills"
            />
          </div>
        </div>
      </section>

      {/* Category nav */}
      <nav className="kdense-cats" aria-label="Skill categories">
        <button
          className={`kdense-cat ${activeCategory === "全部" ? "active" : ""}`}
          onClick={() => setActiveCategory("全部")}
        >
          All <span className="kdense-cat-count">{skills.length}</span>
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
          <p className="kdense-loading">Loading…</p>
        ) : filtered.length === 0 ? (
          <p className="kdense-empty">No matching skills found.</p>
        ) : (
          <div className="kdense-groups">
            {grouped.map(([cat, catSkills]) => (
              <section key={cat} className="kdense-group">
                <h2 className="kdense-group-title">
                  <CategoryIcon category={cat} size={26} />
                  <span className="kdense-group-name">{cat}</span>
                  <span className="kdense-group-count">{catSkills.length}</span>
                </h2>
                <div className="kdense-grid">
                  {catSkills.map((s) => (
                    <SkillCard key={s.name} skill={s} />
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

function SkillCard({ skill }: { skill: Skill }) {
  const [expanded, setExpanded] = useState(false);
  const color = CATEGORY_COLORS[skill.category] || "#636e72";

  return (
    <article className={`kdense-card ${expanded ? "expanded" : ""}`}>
      <div className="kdense-card-accent" style={{ backgroundColor: color }} />
      <div className="kdense-card-body">
        <div className="kdense-card-head">
          <h3 className="kdense-card-name">{skill.name}</h3>
          <span className="kdense-card-license">{skill.license || "MIT"}</span>
        </div>
        <p className="kdense-card-desc">{skill.description || "No description available."}</p>
        {expanded && skill.detail && (
          <div className="kdense-card-detail">
            <p>{skill.detail}</p>
            {(skill.ref_count > 0 || skill.file_count > 0) && (
              <p className="kdense-card-meta">
                {skill.file_count} files{skill.ref_count > 0 && ` · ${skill.ref_count} references`}
              </p>
            )}
          </div>
        )}
        <div className="kdense-card-actions">
          <button
            className="kdense-btn kdense-btn-toggle"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "Collapse" : "Details"}
          </button>
          <a
            className="kdense-btn kdense-btn-github"
            href={`${GITHUB_TREE_BASE}/${skill.github_path}`}
            target="_blank"
            rel="noopener noreferrer"
          >
            Source
          </a>
          <a
            className="kdense-btn kdense-btn-download"
            href={`${GITHUB_RAW_BASE}/${skill.github_path}/SKILL.md`}
            download={`${skill.name}-SKILL.md`}
          >
            Download
          </a>
        </div>
      </div>
    </article>
  );
}
