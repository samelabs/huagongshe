#!/usr/bin/env node
/**
 * build-brand-assets.mjs — 从 web/public/brand/*.svg 生成全站图标（DESIGN_SYSTEM §2）。
 *
 *   cd web && node scripts/build-brand-assets.mjs
 *
 * 依赖仓库内的 sharp（web/node_modules），不新增依赖。SVG 源文件与产物都入库；
 * 改品牌先改 public/brand/ 源文件，再重跑本脚本。产物清单：
 *
 *   public/favicon.ico            16(mark-16)/32(mark)/48(mark)，PNG-in-ICO
 *   app/icon.png                  512 透明底 hgs-mark.svg
 *   app/apple-icon.png            180 直角满底渐变 + 白色线框图形标 62% 宽
 *                                 （iOS 自己加圆角，这里必须直角满底）
 *   public/icon-192.png           192 hgs-app-icon.svg（带圆角）
 *   public/icon-512.png           512 hgs-app-icon.svg（带圆角）
 *   public/icon-maskable-512.png  512 直角满底渐变 + 图形标 50% 宽（maskable 安全区）
 *   public/og.png                 1200×630 白底竖版组合 + “化工社 · AI 化学工作台”
 *   public/logo.png               512 透明底 hgs-mark.svg（保留文件名兼容外部引用）
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const brandDir = path.join(webRoot, "public", "brand");
const publicDir = path.join(webRoot, "public");
const appDir = path.join(webRoot, "app");
const read = (name) => fs.readFileSync(path.join(brandDir, name), "utf8");

/** 渐变底（与 hgs-app-icon.svg 的 linearGradient 相同） */
const GRADIENT_DEFS =
  '<defs><linearGradient id="g" x1="0" y1="0" x2=".35" y2="1">' +
  '<stop offset="0" stop-color="#2B98FF"/><stop offset="1" stop-color="#1468D0"/>' +
  "</linearGradient></defs>";

/** hgs-mark-line.svg 的内部图形（polygon + 白色横画组），currentColor */
const lineMarkInner = read("hgs-mark-line.svg").replace(/<\/?svg[^>]*>|<title>.*?<\/title>/g, "");

/** 剥掉根 svg 标签与 title，保留内部路径（用于按目标尺寸重组） */
const wordmarkInner = read("hgs-wordmark.svg").replace(/<\/?svg[^>]*>|<title>.*?<\/title>/g, "");

/** 把 SVG 根标签的 width/height 改成 target 后交给 sharp（librsvg 按目标尺寸矢量渲染，不走位图缩放） */
async function renderSvgAt(svgText, targetPx) {
  const resized = svgText.replace(
    /<svg([^>]*?)width="\d+" height="\d+"/,
    `<svg$1width="${targetPx}" height="${targetPx}"`,
  );
  return sharp(Buffer.from(resized)).png().toBuffer();
}

/** 直角满底渐变 + 居中白色线框图形标（apple-icon / maskable 共用） */
function gradientTileSvg(size, markWidthRatio) {
  const markW = size * markWidthRatio;
  const scale = markW / 32;
  const offset = (size - markW) / 2;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">` +
    GRADIENT_DEFS +
    `<rect width="${size}" height="${size}" fill="url(#g)"/>` +
    `<g transform="translate(${offset} ${offset}) scale(${scale})" color="#FFFFFF">${lineMarkInner}</g>` +
    `</svg>`
  );
}

/** 最小 ICO 打包：PNG 载荷（Vista+ 通用），无需外部依赖 */
function packIco(entries) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(entries.length, 4);
  const dirs = [];
  let offset = 6 + 16 * entries.length;
  for (const e of entries) {
    const dir = Buffer.alloc(16);
    dir[0] = e.size >= 256 ? 0 : e.size;
    dir[1] = e.size >= 256 ? 0 : e.size;
    dir.writeUInt16LE(1, 4); // color planes
    dir.writeUInt16LE(32, 6); // bpp
    dir.writeUInt32LE(e.png.length, 8);
    dir.writeUInt32LE(offset, 12);
    offset += e.png.length;
    dirs.push(dir);
  }
  return Buffer.concat([header, ...dirs, ...entries.map((e) => e.png)]);
}

/** og.png 的竖版组合：图形标 160 + 字标宽 240（--font-ui 字体栈，字色 n-700） */
const FONT_UI =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'HarmonyOS Sans SC', 'Microsoft YaHei', 'Noto Sans SC', sans-serif";
function ogSvg() {
  const MARK = 160; // 图形标高度
  const WORD_W = 240; // 字标宽度
  const wordH = (WORD_W / 109) * 40; // ≈ 87.9
  const GAP = 24; // 图形标 ↔ 字标
  const TEXT_GAP = 44; // 字标 ↔ 文案
  const blockH = MARK + GAP + wordH + TEXT_GAP + 28;
  const y0 = Math.round((630 - blockH) / 2);
  const wordY = y0 + MARK + GAP;
  const textBaseline = Math.round(wordY + wordH + TEXT_GAP + 22); // baseline ≈ 视觉居中
  const wordScale = WORD_W / 109;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">` +
    `<rect width="1200" height="630" fill="#FFFFFF"/>` +
    // 图形标：直接内嵌 hgs-mark.svg 全文，按 160 定位
    `<g transform="translate(${(1200 - MARK) / 2} ${y0}) scale(${MARK / 32})">` +
    read("hgs-mark.svg").replace(/<\/?svg[^>]*>|<title>.*?<\/title>/g, "") +
    `</g>` +
    // 字标：currentColor → 包一层 color=n-900(#16263A, 同 hgs-lockup.svg)
    `<g transform="translate(${(1200 - WORD_W) / 2} ${wordY.toFixed(2)}) scale(${wordScale.toFixed(6)})" color="#16263A">${wordmarkInner}</g>` +
    `<text x="600" y="${textBaseline}" text-anchor="middle" font-family="${FONT_UI}" font-size="28" fill="#33475D">化工社 · AI 化学工作台</text>` +
    `</svg>`
  );
}

const markSvg = read("hgs-mark.svg");
const appIconSvg = read("hgs-app-icon.svg");

const outputs = [
  // favicon：16 用 mark-16 简化版，32/48 用完整 mark
  async () =>
    fs.writeFileSync(
      path.join(publicDir, "favicon.ico"),
      packIco([
        { size: 16, png: await renderSvgAt(read("hgs-mark-16.svg"), 16) },
        { size: 32, png: await renderSvgAt(markSvg, 32) },
        { size: 48, png: await renderSvgAt(markSvg, 48) },
      ]),
    ),
  async () => fs.writeFileSync(path.join(appDir, "icon.png"), await renderSvgAt(markSvg, 512)),
  async () =>
    fs.writeFileSync(
      path.join(appDir, "apple-icon.png"),
      await sharp(Buffer.from(gradientTileSvg(180, 0.62))).png().toBuffer(),
    ),
  async () => fs.writeFileSync(path.join(publicDir, "icon-192.png"), await renderSvgAt(appIconSvg, 192)),
  async () => fs.writeFileSync(path.join(publicDir, "icon-512.png"), await renderSvgAt(appIconSvg, 512)),
  async () =>
    fs.writeFileSync(
      path.join(publicDir, "icon-maskable-512.png"),
      await sharp(Buffer.from(gradientTileSvg(512, 0.5))).png().toBuffer(),
    ),
  async () =>
    fs.writeFileSync(path.join(publicDir, "og.png"), await sharp(Buffer.from(ogSvg())).png().toBuffer()),
  async () => fs.writeFileSync(path.join(publicDir, "logo.png"), await renderSvgAt(markSvg, 512)),
];

for (const build of outputs) await build();
const produced = [
  "public/favicon.ico",
  "app/icon.png",
  "app/apple-icon.png",
  "public/icon-192.png",
  "public/icon-512.png",
  "public/icon-maskable-512.png",
  "public/og.png",
  "public/logo.png",
];
for (const rel of produced) {
  const abs = path.join(webRoot, rel);
  if (rel.endsWith(".ico")) {
    // sharp 不读 ICO；直接解析目录项报尺寸
    const buf = fs.readFileSync(abs);
    const entries = buf.readUInt16LE(4);
    const sizes = Array.from({ length: entries }, (_, i) => {
      const s = buf[6 + i * 16];
      return s === 0 ? 256 : s;
    });
    console.log(`${rel}  ico ${sizes.join("/")}  ${buf.length}B`);
    continue;
  }
  const meta = await sharp(abs).metadata();
  console.log(`${rel}  ${meta.format} ${meta.width}×${meta.height}  ${fs.statSync(abs).size}B`);
}
console.log(`\n${produced.length} brand assets rebuilt from public/brand/*.svg`);
