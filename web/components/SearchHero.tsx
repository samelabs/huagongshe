"use client";

/**
 * SearchHero — 大搜索框 + 检索方式 Segmented（v1.7 Step 10，§9.3 / Discovery）。
 * 首页与 /search 共用：高 48 输入框（圆角 r-md、左图标）+「查询」primary lg；
 * 下方 Segmented：名称/CAS · 精确结构 · 子结构 · 相似结构。
 *
 * 模式随查询带进 /search 的 URL（?q=…&mode=…）。结构类模式（structure /
 * substructure / similarity）未登录时点查询 → 登录页带回跳地址（与化合物页
 * 子结构/相似结构按钮的行为一致，入口统一收口在这一个组件）。
 * 注：「精确结构」= SMILES 恒等匹配，API 无独立 mode，/search 服务端映射回
 * exact（URL 保留 structure 以回显 Segmented 选择）。
 */
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useDictionary, useLocale } from "@/components/shared/I18nContext";
import { withLocale } from "@/lib/localePath";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { IconSearch } from "@/components/ui/icons";

export type SearchHeroMode = "exact" | "structure" | "substructure" | "similarity";

const MODES: SearchHeroMode[] = ["exact", "structure", "substructure", "similarity"];
const STRUCTURE_MODES: SearchHeroMode[] = ["structure", "substructure", "similarity"];

export function normalizeSearchMode(value: string | undefined | null): SearchHeroMode {
  return MODES.includes(value as SearchHeroMode) ? (value as SearchHeroMode) : "exact";
}

export function SearchHero({ initial = "", initialMode = "exact", authed, autoFocus = false, contextLabel }: {
  initial?: string;
  initialMode?: SearchHeroMode;
  /** 服务端 cookie 判定；未登录时结构类模式点查询去登录页 */
  authed: boolean;
  /** 挂载即聚焦输入框（/search?focus=1） */
  autoFocus?: boolean;
  /** 输入框 aria-label（首页/搜索页文案不同时用） */
  contextLabel?: string;
}) {
  const router = useRouter();
  const t = useDictionary();
  const locale = useLocale();
  const [query, setQuery] = useState(initial);
  const [mode, setMode] = useState<SearchHeroMode>(normalizeSearchMode(initialMode));
  const inputRef = useRef<HTMLInputElement>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) { inputRef.current?.focus(); return; }
    const target = withLocale(`/search?q=${encodeURIComponent(q)}${mode !== "exact" ? `&mode=${mode}` : ""}`, locale);
    if (STRUCTURE_MODES.includes(mode) && !authed) {
      router.push(withLocale(`/login?next=${encodeURIComponent(target)}`, locale));
      return;
    }
    router.push(target);
  }

  const modeLabel: Record<SearchHeroMode, string> = {
    exact: t.search.modeNameCas,
    structure: t.search.modeExactStructure,
    substructure: t.search.modeSubstructure,
    similarity: t.search.modeSimilarity,
  };

  return (
    <div className="srch-hero">
      <form className="srch-box" onSubmit={submit}>
        <div className="srch-box-wrap">
          <IconSearch />
          <input
            ref={inputRef}
            type="text"
            autoFocus={autoFocus}
            enterKeyHint="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t.search.placeholder}
            aria-label={contextLabel ?? t.search.title}
            autoComplete="off"
            spellCheck={false}
            maxLength={4000}
          />
        </div>
        <Button variant="primary" size="lg" type="submit">{t.home.searchButton}</Button>
      </form>
      <Segmented
        className="srch-modes"
        ariaLabel={t.search.modeLabel}
        options={MODES.map((value) => ({ value, label: modeLabel[value] }))}
        value={mode}
        onChange={(value) => setMode(value)}
      />
    </div>
  );
}
