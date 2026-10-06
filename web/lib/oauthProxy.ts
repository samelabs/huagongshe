import { NextRequest, NextResponse } from "next/server";

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";
const HOP_BY_HOP = new Set([
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade", "host",
]);

/**
 * Root OAuth discovery/authorization endpoints must stay on huagongshe.com
 * while FastAPI remains private. This adapter is transport-only: cookies,
 * form bodies and redirects are forwarded without making auth decisions.
 */
export async function proxyOAuth(
  request: NextRequest,
  backendPath: string,
): Promise<NextResponse> {
  const incoming = new Headers();
  for (const key of ["cookie", "authorization", "content-type", "accept", "user-agent"]) {
    const value = request.headers.get(key);
    if (value != null) incoming.set(key, value);
  }

  const url = new URL(request.url);
  const target = `${API_ORIGIN}/api/oauth/${backendPath}${url.search}`;
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
    return NextResponse.json({ error: "server_error" }, { status: 502 });
  }

  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (!HOP_BY_HOP.has(lower) && lower !== "content-length" && lower !== "content-encoding") {
      headers.set(key, value);
    }
  });
  return new NextResponse(upstream.body, { status: upstream.status, headers });
}
