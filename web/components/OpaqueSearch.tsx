// 诊断实验组件 (React host ownership 隔离)。
// React 只拥有外层容器; 内部 form/input/button 全部由
// dangerouslySetInnerHTML 注入, 不建立 host fiber/props/events/
// valueTracker/own value descriptor (本地 production build 已实测)。
// 提交走原生 GET /search?q=..., 无任何 JS。
// 实验期简化: input 不回显当前 q (避免动态 value 的转义面)。
import t from "@/lib/i18n";

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function OpaqueSearch({ compact = false }: { compact?: boolean }) {
  const placeholder = compact ? t.search.hintNameShort : t.home.searchPlaceholder;
  const ariaLabel = t.search.title;
  const buttonText = t.home.searchButton;
  const inner = `
    <form class="search-row" action="/search" method="get">
      <div class="search-input-box">
        <svg class="search-input-box__icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.5" y2="16.5"></line></svg>
        <input type="text" name="q" enterkeyhint="search" placeholder="${escapeHtml(placeholder)}" aria-label="${escapeHtml(ariaLabel)}" autocomplete="off" spellcheck="false" maxlength="4000">
      </div>
      <button type="submit" class="search-submit-btn">${escapeHtml(buttonText)}</button>
    </form>`;
  return (
    <div
      className={`search-wrap${compact ? " search-wrap--compact" : ""}`}
      data-probe-shell="opaque-search"
      dangerouslySetInnerHTML={{ __html: inner }}
    />
  );
}
