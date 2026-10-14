import { NextRequest, NextResponse } from "next/server";
import { ALLOWED_MOL_SVG_DIMS } from "@/lib/molSizes";

/**
 * 分子结构图资产路由（B2 通道规范；Round 13 白名单与公开长缓存收口）：
 * 浏览器经 Next 同源取图；本 handler loopback 直连 FastAPI（无 XFF = T0）。
 * - 尺寸白名单：仅接受 ALLOWED_MOL_SVG_DIMS 定义的固定档位，其余 404。
 * - 缓存策略：化合物当前无私有态，不再转发 cookie，统一为公开不可变长缓存
 *   public, max-age=31536000, immutable。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  const match = dims.match(/^(\d+x\d+)\.svg$/);
  if (!/^\d+$/.test(id) || !match || !ALLOWED_MOL_SVG_DIMS.has(match[1])) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [w, h] = match[1].split("x");

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/mol/${id}/svg?w=${w}&h=${h}`,
      {
        cache: "no-store",
        headers: {
          "accept": "image/svg+xml",
        },
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
      "content-type": "image/svg+xml",
      "cache-control": "public, max-age=31536000, immutable",
    },
  });
}
