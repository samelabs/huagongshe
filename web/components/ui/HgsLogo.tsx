/**
 * HgsLogo — HGS 标志(DESIGN_SYSTEM §2)的唯一 React 实现。
 *
 *   <HgsLogo variant="lockup" | "mark" | "wordmark" size={28} locale={locale} />
 *
 * - size 是图形标高度(默认 28);lockup 中字标高度 = size × 0.68,水平间距 10。
 * - lockup 仅在 locale === "zh-CN" 时渲染「1px×16 分隔线 + 化工社」副标;
 *   ≤640px 由 globals.css 的 .hgs-logo 媒体规则缩到 24 并隐藏副标。
 * - 图形标颜色 var(--brand),字标 currentColor(由外层 header 决定)。
 * - SVG geometry 与 web/public/brand/hgs-mark.svg / hgs-wordmark.svg 逐字一致,
 *   被 tests/test_ui_token_contract.py BrandAssetTests 钉死——改路径先改品牌源文件。
 * - SVG aria-hidden:可访问名称由外层链接提供(aria-label={t.nav.home})。
 */

export type HgsLogoVariant = "lockup" | "mark" | "wordmark";

export interface HgsLogoProps {
  variant: HgsLogoVariant;
  /** 图形标高度 px;默认 28(网站顶栏) */
  size?: number;
  /** 当前 locale;仅 "zh-CN" 时 lockup 渲染中文副标 */
  locale?: string;
}

const WORDMARK_RATIO = 109 / 40;

function HgsMark({ size, className }: { size: number; className: string }) {
  return (
    <svg className={className} viewBox="0 0 32 32" width={size} height={size} aria-hidden="true">
      <polygon
        points="16,3 27.26,9.5 27.26,22.5 16,29 4.74,22.5 4.74,9.5"
        fill="var(--brand)"
        stroke="var(--brand)"
        strokeWidth="3.2"
        strokeLinejoin="round"
      />
      <g fill="#FFFFFF">
        <rect x="10.2" y="9.6" width="2.9" height="12.8" rx=".4" />
        <rect x="18.9" y="9.6" width="2.9" height="12.8" rx=".4" />
        <rect x="13" y="13.4" width="6" height="1.7" />
        <rect x="13" y="16.9" width="6" height="1.7" />
      </g>
    </svg>
  );
}

function HgsWordmark({ height, className }: { height: number; className: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 109 40"
      width={Math.round(height * WORDMARK_RATIO * 100) / 100}
      height={Math.round(height * 100) / 100}
      aria-hidden="true"
    >
      <g fill="none" stroke="currentColor" strokeWidth="7">
        <path d="M3.5 0V40M26.5 0V40M3.5 20H26.5" />
        <path d="M70.26 8.96A16.5 16.5 0 1 0 74.5 20H60" />
        <path d="M103.51 7.02A8.25 8.25 0 1 0 96.75 20A8.25 8.25 0 1 1 89.99 32.98" />
      </g>
    </svg>
  );
}

export function HgsLogo({ variant, size = 28, locale }: HgsLogoProps) {
  if (variant === "mark") {
    return <HgsMark size={size} className="hgs-logo-mark" />;
  }
  if (variant === "wordmark") {
    return <HgsWordmark height={size} className="hgs-logo-wordmark" />;
  }
  return (
    <span className="hgs-logo">
      <HgsMark size={size} className="hgs-logo-mark" />
      <HgsWordmark height={size * 0.68} className="hgs-logo-wordmark" />
      {locale === "zh-CN" && (
        <span className="hgs-logo-zh">
          <span className="hgs-logo-divider" />
          <span className="hgs-logo-zh-text">化工社</span>
        </span>
      )}
    </span>
  );
}
