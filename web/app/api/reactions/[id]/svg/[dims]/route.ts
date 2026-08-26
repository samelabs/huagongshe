import { NextRequest, NextResponse } from "next/server";

/**
 * 反应方程式图资产路由（B2 通道规范）：
 * 与分子图同机制：Next 资产 + immutable 缓存，loopback 拉 FastAPI（T0）。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(_request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  if (!/^\d+$/.test(id) || !/^\d+x\d+\.svg$/.test(dims)) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [w, h] = dims.replace(/\.svg$/, "").split("x");

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/reactions/${id}/svg?w=${w}&h=${h}`,
      { cache: "no-store", headers: { "accept": "image/svg+xml" } },
    );
  } catch {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
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
