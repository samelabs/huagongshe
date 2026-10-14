/**
 * 化合物结构图标准尺寸档位与白名单（DESIGN_SYSTEM 公开资源规范）
 *
 * 全站收敛为 4 档 4:3 比例尺寸：
 * - lg (280×210): 化合物详情页结构大卡片
 * - md (160×120): 搜索结果、工作台面板中型卡片
 * - sm (112×84):  实体卡片、工作台收藏列表等小卡片
 * - xs (64×48):   反应参与物缩略图、工作台首页微缩图
 */

export const MOL_SVG_SIZES = {
  lg: { width: 280, height: 210 },
  md: { width: 160, height: 120 },
  sm: { width: 112, height: 84 },
  xs: { width: 64, height: 48 },
} as const;

export type MolSvgSizeKey = keyof typeof MOL_SVG_SIZES;

/** 结构图 URL 允许的尺寸白名单集合（宽x高，不含 .svg） */
export const ALLOWED_MOL_SVG_DIMS: ReadonlySet<string> = new Set([
  "280x210",
  "160x120",
  "112x84",
  "64x48",
]);

/** 化合物分享图允许的固定尺寸（宽x高，不含 .png） */
export const MOL_SHARE_PNG_DIMS = "800x800";

/** 反应分享图允许的固定尺寸白名单集合（宽x高，不含 .png） */
export const ALLOWED_REACTION_SHARE_PNG_DIMS: ReadonlySet<string> = new Set([
  "1200x630",
  "800x800",
]);
