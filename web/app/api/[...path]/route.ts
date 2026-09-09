import { NextRequest, NextResponse } from "next/server";

/**
 * BFF 统一入口：浏览器只与 Next 同源对话，FastAPI 从公网消失。
 *
 * 通道语义（H1 方案 D）：
 * - BFF 是 transport proxy，不授予 FastAPI 权限；authorization 由
 *   FastAPI actor/public policy 决定（loopback 不再是 authorization
 *   evidence）。
 * - Cookie / Authorization 原样透传：登录用户身份由 FastAPI 侧既有
 *   optional_actor / current_actor 解析，本层不做任何鉴权判断。
 * - 公开数据匿名完整体验：匿名分页与本页数据走同一通道，无需身份。
 * - 防御性规则：inbound x-hgs-* 一律不向 FastAPI 转发 —— 任何未来的
 *   X-HGS 机制不得因经此代理而自动获得可信地位。
 * - /api/docs /api/openapi.json /api/redoc 本层 404：MCP 发现机制是
 *   /api/agent-guide 自描述文档，不是 OpenAPI。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade", "host",
]);

const FORWARDED_HEADERS = [
  "cookie", "authorization", "content-type", "content-length",
  "accept", "accept-language", "user-agent", "if-none-match", "if-modified-since",
];

function notFound(): NextResponse {
  return NextResponse.json({ detail: "Not Found" }, { status: 404 });
}

async function proxy(request: NextRequest, path: string): Promise<NextResponse> {
  // MCP 发现面收口：OpenAPI/文档不暴露
  if (path === "/api/docs" || path === "/api/openapi.json" || path === "/api/redoc" || path.startsWith("/api/redoc/")) {
    return notFound();
  }

  const incoming = new Headers();
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (
      !HOP_BY_HOP.has(lower) &&
      !FORWARDED_HEADERS.includes(lower) &&
      lower !== "x-forwarded-for" && lower !== "x-forwarded-proto" && lower !== "x-real-ip" &&
      !lower.startsWith("x-hgs-")
    ) {
      incoming.set(key, value);
    }
  });
  for (const key of FORWARDED_HEADERS) {
    const value = request.headers.get(key);
    if (value != null) incoming.set(key, value);
  }

  const url = new URL(request.url);
  const target = `${API_ORIGIN}${url.pathname}${url.search}`;

  const body = request.method === "GET" || request.method === "HEAD"
    ? undefined
    : await request.arrayBuffer();

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers: incoming,
      body,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "上游服务不可用" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!HOP_BY_HOP.has(lower) && lower !== "content-encoding" && lower !== "content-length") {
      responseHeaders.set(key, value);
    }
  });
  // Set-Cookie 逐条回传（Headers 合并会破坏多 cookie）
  const setCookies = upstream.headers.getSetCookie?.() ?? [];
  for (const cookie of setCookies) {
    responseHeaders.append("set-cookie", cookie);
  }

  return new NextResponse(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, `/api/${path.join("/")}`);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, `/api/${path.join("/")}`);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, `/api/${path.join("/")}`);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, `/api/${path.join("/")}`);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, `/api/${path.join("/")}`);
}

export async function HEAD(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxy(request, `/api/${path.join("/")}`);
}
