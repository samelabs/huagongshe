import { NextRequest, NextResponse } from "next/server";

/**
 * 化合物公开图片路由：/img/chemical/{id}.svg 与 /img/chemical/{id}.png。
 *
 * - SVG 是矢量图：地址不带尺寸，显示尺寸由页面 CSS 决定；内部按固定画布渲染。
 * - PNG 是 1:1 分享图（800×800，白底，四周留白），供社交平台抓取。
 * - 化合物结构图没有私有态：不转发 cookie，公开不可变长缓存。
 * - 没有可渲染结构时返回 404，不在路由里替换成其他图片。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

const SVG_CANVAS = { w: 800, h: 600 };
const SHARE_PNG_SIZE = 800;

type RouteContext = { params: Promise<{ file: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { file } = await context.params;
  const match = file.match(/^(\d+)\.(svg|png)$/);
  if (!match) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [, id, kind] = match;

  const query = kind === "svg"
    ? `w=${SVG_CANVAS.w}&h=${SVG_CANVAS.h}`
    : `w=${SHARE_PNG_SIZE}&h=${SHARE_PNG_SIZE}`;

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/mol/${id}/${kind}?${query}`,
      {
        cache: "no-store",
        headers: { accept: kind === "svg" ? "image/svg+xml" : "image/png" },
      },
    );
  } catch {
    return NextResponse.json({ detail: "上游服务不可用" }, { status: 502 });
  }
  if (upstream.status !== 200) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type": kind === "svg" ? "image/svg+xml" : "image/png",
      "cache-control": "public, max-age=31536000, immutable",
    },
  });
}
