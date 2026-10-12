import { NextRequest, NextResponse } from "next/server";

/**
 * 分子结构图资产路由（B2 通道规范）：
 * 浏览器经 Next 同源取图；本 handler loopback 直连 FastAPI（无 XFF = T0）。
 * 请求 cookie 原样透传（与通用 BFF 通道 FORWARDED_HEADERS 做法一致）——
 * 化合物当前无私有态，透传只是通道语义统一。
 * 缓存策略：匿名（无 cookie）→ SVG 是确定性派生物（RDKit 渲染存储的
 * SMILES，同参数恒同图），immutable 缓存语义精确；带 cookie → 恒
 * private, no-store，带身份的响应不进任何共享缓存。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  // 参数形状校验：与 nginx 旧伪静态规则一致 \d+x\d+
  if (!/^\d+$/.test(id) || !/^\d+x\d+\.svg$/.test(dims)) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [w, h] = dims.replace(/\.svg$/, "").split("x");
  const cookie = request.headers.get("cookie");

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/mol/${id}/svg?w=${w}&h=${h}`,
      {
        cache: "no-store",
        headers: {
          "accept": "image/svg+xml",
          ...(cookie ? { cookie } : {}),
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
      "cache-control": cookie
        ? "private, no-store"
        : "public, max-age=31536000, immutable",
    },
  });
}
