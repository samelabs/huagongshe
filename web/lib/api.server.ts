import "server-only";

import { ApiError } from "@/lib/api";

/**
 * 服务端取数专用层（page / layout / generateMetadata / route handler）。
 *
 * 为什么独立成模块：服务端渲染直连后端（不经浏览器 BFF），请求从 Next
 * 进程发出——后端视角与访客无关。后端按访客 IP 分桶的匿名副作用约束
 * （搜索的库外建行、采集入队等）拿不到访客 IP 时只能跳过，等于 SSR
 * 流量恒为无限流。本层把入站请求的访客身份（nginx 覆盖写入的
 * x-real-ip 与 cookie）随取数请求转发，后端按同一访客分桶。
 *
 * 信任前提与 BFF（app/api/[...path]）一致：x-real-ip 由 nginx 用
 * $remote_addr 覆盖写入，客户端伪造不了；x-forwarded-for 首段可伪造，
 * 一律不读不转发。
 *
 * 缓存不变量：带 revalidate 的取数是跨请求共享的缓存，不得携带任何
 * 请求作用域身份——此类请求不读入站头、不转发（调用方显式传头时维持
 * 既有契约直接抛错）。无请求作用域（构建期静态生成等）读不到入站头，
 * 同样不转发。
 */

const SERVER_API_BASE =
  process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000/api";

/** 入站请求里需要随取数转发的访客身份 */
export type InboundIdentity = { realIp: string | null; cookie: string | null };

/**
 * 合并转发头（纯函数，供单测锁定规则）：
 * - cookie：入站值作默认，调用方显式传入的（可能收窄过）优先；
 * - x-real-ip：只认入站值且最终生效——它是 nginx 写入的权威身份，
 *   取数调用方不得自行指定。
 */
export function forwardHeaders(caller?: HeadersInit, inbound?: InboundIdentity | null): Headers {
  const merged = new Headers();
  if (inbound?.cookie) merged.set("cookie", inbound.cookie);
  if (caller) new Headers(caller).forEach((value, key) => merged.set(key, value));
  if (inbound?.realIp) merged.set("x-real-ip", inbound.realIp);
  return merged;
}

/** 读取入站请求的访客身份；无请求作用域（静态生成等）返回 null。 */
async function readInbound(): Promise<InboundIdentity | null> {
  try {
    const { headers } = await import("next/headers");
    const h = await headers();
    return { realIp: h.get("x-real-ip"), cookie: h.get("cookie") };
  } catch {
    return null;
  }
}

async function safeDetail(response: Response): Promise<unknown> {
  try {
    return await response.clone().json();
  } catch {
    return undefined;
  }
}

/** 服务端取数：与客户端 apiGet 同签名。差异只在身份头（见模块注释）。 */
export async function apiGet<T>(path: string, headers?: HeadersInit, opts?: { revalidate?: number }): Promise<T> {
  if (opts?.revalidate != null && headers) {
    throw new Error(`apiGet: refusing cached request with headers (${path})`);
  }
  // 缓存取数不读入站头：共享缓存不得携带请求作用域身份
  const inbound = opts?.revalidate != null ? null : await readInbound();
  const response = await fetch(`${SERVER_API_BASE}${path}`, {
    headers: inbound || headers ? forwardHeaders(headers, inbound) : undefined,
    ...(opts?.revalidate != null
      ? { next: { revalidate: opts.revalidate } }
      : { cache: "no-store" }),
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const inbound = await readInbound();
  const merged = forwardHeaders(headers, inbound);
  if (!(body instanceof FormData) && !merged.has("content-type")) merged.set("Content-Type", "application/json");
  const response = await fetch(`${SERVER_API_BASE}${path}`, {
    method: "POST",
    headers: merged,
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiPatch<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const inbound = await readInbound();
  const merged = forwardHeaders(headers, inbound);
  if (!(body instanceof FormData) && !merged.has("content-type")) merged.set("Content-Type", "application/json");
  const response = await fetch(`${SERVER_API_BASE}${path}`, {
    method: "PATCH",
    headers: merged,
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiDelete<T>(path: string, headers?: HeadersInit): Promise<T> {
  const inbound = await readInbound();
  const response = await fetch(`${SERVER_API_BASE}${path}`, {
    method: "DELETE",
    headers: forwardHeaders(headers, inbound),
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export async function apiPut<T>(path: string, body?: BodyInit, headers?: HeadersInit): Promise<T> {
  const inbound = await readInbound();
  const merged = forwardHeaders(headers, inbound);
  if (!(body instanceof FormData) && !merged.has("content-type")) merged.set("Content-Type", "application/json");
  const response = await fetch(`${SERVER_API_BASE}${path}`, {
    method: "PUT",
    headers: merged,
    body,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status, path, await safeDetail(response));
  return response.status === 204 ? undefined as T : await response.json() as T;
}
