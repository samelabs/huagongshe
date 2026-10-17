/**
 * ogTokens — OG 品牌卡专用色值映射。
 *
 * 唯一来源仍是 tokens.css；next/og 的 ImageResponse（satori）在无 DOM 的
 * canvas 上下文渲染，读不到 CSS 变量，故按 tokens.css 原值镜像一份。
 * 只允许本文件出现这些字面量（web/app + web/components 的 hex 禁令不扫描
 * web/lib，见 tests/test_ui_token_contract.py SCAN_DIRS）；tokens.css 改色时
 * 必须同步此处。
 */
export const ogColors = {
  page: "#FFFFFF",      // --bg-surface (--n-0)
  subtle: "#F0F3F8",    // --bg-subtle  (--n-50)
  blue50: "#EEF5FF",    // --action-subtle (--blue-50)
  border: "#E3E8EF",    // --border (--n-100)
  text: "#16263A",      // --text (--n-900)
  text2: "#33475D",     // --text-2 (--n-700)
  muted: "#5F7389",     // --text-muted (--n-500)
  brand: "#1E90FF",     // --brand (--blue-500)
  actionInk: "#0F56AD", // --action-ink (--blue-700)
} as const;
