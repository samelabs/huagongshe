import { NextRequest, NextResponse } from "next/server";

/**
 * BFF 统一入口：浏览器只与 Next 同源对话，FastAPI 从公网消失。
 *
 * 通道语义（API 通道规范 B2）：
 * - 本 handler 是服务端请求：loopback 直连 FastAPI，不带 X-Forwarded-For，
 *   FastAPI 视角恒为内部流量（无 XFF = T0）。
 * - Cookie / Authorization 原样透传：登录用户身份由 FastAPI 侧既有
 *   optional_actor / current_actor 解析，本层不做任何鉴权判断。
 * - 公开数据匿名完整体验：匿名分页与本页数据走同一通道，无需身份。
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
  if (path === "/api/docs" || path === "/api/openapi.json" || path === "/api/redoc" || path === "/api/redoc/*") {
    return notFound();
  }

  const incoming = new Headers();
  request.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!HOP_BY_HOP.has(lower) && !FORWARDED_HEADERS.includes(lower) && lower !== "x-forwarded-for" && lower !== "x-forwarded-proto" && lower !== "x-real-ip") {
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
