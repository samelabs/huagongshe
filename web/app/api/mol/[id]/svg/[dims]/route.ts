import { NextRequest, NextResponse } from "next/server";

/**
 * 分子结构图资产路由（B2 通道规范）：
 * 浏览器经 Next 同源取图；本 handler loopback 直连 FastAPI（无 XFF = T0）。
 * SVG 是确定性派生物（RDKit 渲染存储的 SMILES，同参数恒同图），
 * 故 immutable 缓存语义精确；Next data cache 兜底，重复请求不打 API。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(_request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  // 参数形状校验：与 nginx 旧伪静态规则一致 \d+x\d+
  if (!/^\d+$/.test(id) || !/^\d+x\d+\.svg$/.test(dims)) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [w, h] = dims.replace(/\.svg$/, "").split("x");

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/mol/${id}/svg?w=${w}&h=${h}`,
      { cache: "no-store", headers: { "accept": "image/svg+xml" } },
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
