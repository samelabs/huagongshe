import { NextRequest, NextResponse } from "next/server";

/**
 * 反应方程式图资产路由（B2 通道规范；D002 修复 R1）：
 * loopback 拉 FastAPI（T0）。Cookie / Authorization 原样透传（与通用 BFF
 * 通道 web/app/api/[...path]/route.ts 的 FORWARDED_HEADERS 做法一致）——
 * 私有反应的可见性由 FastAPI 侧 public_or_actor 判定，BFF 不做鉴权。
 * 带身份的响应绝不落共享缓存：请求带 cookie 时响应恒为
 * private, no-store（忽略 upstream 的公开缓存头）。
 * 匿名请求维持 Cache-Control 以 backend 为 canonical owner:
 * upstream 200 → 逐字 passthrough; 缺失时安全降级 private, no-store
 * （禁止 BFF 强化为 public 长缓存——转私有/撤稿一致性窗口由 backend 定义）。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  if (!/^\d+$/.test(id) || !/^\d+x\d+\.svg$/.test(dims)) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [w, h] = dims.replace(/\.svg$/, "").split("x");
  const cookie = request.headers.get("cookie");

  let upstream: Response;
  try {
    upstream = await fetch(
      `${API_ORIGIN}/api/reactions/${id}/svg?w=${w}&h=${h}`,
      {
        cache: "no-store",
        headers: {
          "accept": "image/svg+xml",
          ...(cookie ? { cookie } : {}),
        },
      },
    );
  } catch {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  if (upstream.status !== 200) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  // 带会话 cookie → 该响应可能包含私有数据，禁止任何中间层共享缓存
  if (cookie) {
    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "content-type": "image/svg+xml",
        "cache-control": "private, no-store",
      },
    });
  }
  // D002 (R1): upstream Cache-Control passthrough — BFF 不强化缓存策略。
  const upstreamCacheControl = upstream.headers.get("cache-control");
  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "content-type": "image/svg+xml",
      "cache-control": upstreamCacheControl || "private, no-store",
    },
  });
}
