import { NextRequest, NextResponse } from "next/server";
import { MOL_SHARE_PNG_DIMS } from "@/lib/molSizes";

/**
 * 化合物分享图资产路由（DESIGN_SYSTEM 公开资源规范；Round 13）：
 * 浏览器与社交平台爬虫经 Next 同源获取。
 * - 仅支持固定尺寸 800x800.png（白底方形留白），其余 404。
 * - 内部 loopback 请求后端 /api/mol/{id}/png?w=800&h=800（不转 cookie）。
 * - 缓存策略：不可变长缓存 public, max-age=31536000, immutable。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  const match = dims.match(/^(\d+x\d+)\.png$/);
  if (!/^\d+$/.test(id) || !match || match[1] !== MOL_SHARE_PNG_DIMS) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/mol/${id}/png?w=800&h=800`,
      {
        cache: "no-store",
        headers: {
          "accept": "image/png",
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
      "content-type": "image/png",
      "cache-control": "public, max-age=31536000, immutable",
    },
  });
}
