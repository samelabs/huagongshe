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

// 分类中文图标
const CATEGORY_ICONS: Record<string, string> = {
  化学信息学: "⚗️",
  生物信息学: "🧬",
  临床与医学: "🏥",
  "机器学习与AI": "🤖",
  统计分析: "📊",
  科研写作与文献: "📝",
  科学可视化: "🎨",
  数据处理: "🗃️",
  平台集成: "🔌",
  地球与物理科学: "🌍",
  研究方法论: "🔬",
  通用工具: "🛠️",
};

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
      {/* 页头 */}
      <section className="kdense-hero">
        <div className="kdense-hero-inner">
          <p className="kdense-breadcrumb">
            <a href="/">化工社</a>
            <span className="kdense-sep">/</span>
            <span>科学 AI 技能库</span>
          </p>
          <h1>K-Dense 科学 AI 技能库</h1>
          <p className="kdense-subtitle">
            <strong>{skills.length || 158}</strong> 个科学 AI Agent 技能，覆盖化学、生物、ML、科研写作等 12 个领域
          </p>
          <p className="kdense-source">
            数据来源：<a
              href={GITHUB_TREE_BASE}
              target="_blank"
              rel="noopener noreferrer"
            >
              K-Dense-AI/scientific-agent-skills
            </a>{" "}
            (⭐ 32.6k) · MIT 协议 · 由化工社整理呈现
          </p>

          {/* 搜索框 */}
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

      {/* 分类导航 */}
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
            <span className="kdense-cat-icon">
              {CATEGORY_ICONS[cat] || "📦"}
            </span>
            {cat} <span className="kdense-cat-count">{count}</span>
          </button>
        ))}
      </nav>

      {/* 技能列表 */}
      <div className="kdense-content">
        {loading ? (
          <p className="kdense-loading">加载中…</p>
        ) : filtered.length === 0 ? (
          <p className="kdense-empty">未找到匹配的技能</p>
        ) : (
          <div className="kdense-groups">
            {grouped.map(([cat, catSkills]) => (
              <section key={cat} className="kdense-group">
                <h2 className="kdense-group-title">
                  <span className="kdense-group-icon">
                    {CATEGORY_ICONS[cat] || "📦"}
                  </span>
                  {cat}
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

  return (
    <article className={`kdense-card ${expanded ? "expanded" : ""}`}>
      <div className="kdense-card-head">
        <h3 className="kdense-card-name">{skill.name}</h3>
        <span className="kdense-card-license">{skill.license || "MIT"}</span>
      </div>
      <p className="kdense-card-desc">
        {skill.description || "暂无描述"}
      </p>
      {expanded && skill.detail && (
        <div className="kdense-card-detail">
          <p>{skill.detail}</p>
          {(skill.ref_count > 0 || skill.file_count > 0) && (
            <p className="kdense-card-meta">
              📄 {skill.file_count} 个文件
              {skill.ref_count > 0 && ` · 📚 ${skill.ref_count} 个参考文档`}
            </p>
          )}
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
          className="kdense-btn kdense-btn-github"
          href={`${GITHUB_TREE_BASE}/${skill.github_path}`}
          target="_blank"
          rel="noopener noreferrer"
        >
          源码
        </a>
        <a
          className="kdense-btn kdense-btn-download"
          href={`${GITHUB_RAW_BASE}/${skill.github_path}/SKILL.md`}
          download={`${skill.name}-SKILL.md`}
        >
          下载 SKILL.md
        </a>
      </div>
    </article>
  );
}
