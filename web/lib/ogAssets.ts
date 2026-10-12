import { readFile } from "node:fs/promises";
import path from "node:path";

import { SERVER_API_BASE } from "@/lib/api";

/**
 * OG 品牌卡取材 helper（G4 收口）——三个 opengraph-image 路由共用。
 *
 * - logoDataUrl: web/app/icon.png（HGS 标志 512×512）读盘转 data URL；
 *   satori 的 <img> 只接受位图（PNG/JPG/WebP），SVG 走不通。
 * - fetchMolPngDataUrl: 结构图取自现有 /api/mol/{id}/png（不新增 API），
 *   服务端 fetch 后转 data URL；404/失败返回 null（卡片退化为无图版）。
 */

export async function logoDataUrl(): Promise<string | null> {
  try {
    const png = await readFile(path.join(process.cwd(), "app", "icon.png"));
    return `data:image/png;base64,${png.toString("base64")}`;
  } catch {
    return null;
  }
}

export async function fetchMolPngDataUrl(chemicalId: number | string): Promise<string | null> {
  try {
    const response = await fetch(`${SERVER_API_BASE}/mol/${chemicalId}/png`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    if (!response.ok) return null;
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length === 0) return null;
    return `data:image/png;base64,${buffer.toString("base64")}`;
  } catch {
    return null;
  }
}
