import { NextRequest, NextResponse } from "next/server";
import { ImageResponse } from "next/og";

/**
 * 反应公开图片路由：/img/reaction/{id}.svg 与 /img/reaction/{id}.png。
 *
 * - SVG 是矢量图：地址不带尺寸，显示尺寸由页面 CSS 决定。
 * - PNG 是 1200×630 横版分享图（白底居中），供社交平台抓取。
 * - 可见性由后端判定：请求原样转发 cookie，私有反应只有本人/管理员
 * 能取到图；带身份的响应恒为 private, no-store，绝不落共享缓存。
 * - 反应不存在、不公开或没有可渲染的结构表达时返回 404，
 * 不在路由里替换成其他图片。
 */

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

const SVG_CANVAS = { w: 1600, h: 400 };
const SHARE_PNG_SIZE = { w: 1200, h: 630 };

type RouteContext = { params: Promise<{ file: string }> };

async function fetchUpstreamSvg(id: string, cookie: string | null): Promise<Response | null> {
  try {
    return await fetch(
      `${API_ORIGIN}/api/reactions/${id}/svg?w=${SVG_CANVAS.w}&h=${SVG_CANVAS.h}`,
      {
        cache: "no-store",
        headers: {
          accept: "image/svg+xml",
          ...(cookie ? { cookie } : {}),
        },
      },
    );
  } catch {
    return null;
  }
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { file } = await context.params;
  const match = file.match(/^(\d+)\.(svg|png)$/);
  if (!match) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }
  const [, id, kind] = match;
  const cookie = request.headers.get("cookie");

  const upstream = await fetchUpstreamSvg(id, cookie);
  if (!upstream || upstream.status !== 200) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }

  if (kind === "svg") {
    // 带会话 cookie → 该响应可能包含私有数据，禁止任何中间层共享缓存；
    // 匿名请求以后端 Cache-Control 为准（缺失时安全降级 private, no-store）。
    const cacheControl = cookie
      ? "private, no-store"
      : upstream.headers.get("cache-control") || "private, no-store";
    return new NextResponse(upstream.body, {
      status: 200,
      headers: {
        "content-type": "image/svg+xml",
        "cache-control": cacheControl,
      },
    });
  }

  const svgText = await upstream.text();
  const dataUrl = `data:image/svg+xml;base64,${Buffer.from(svgText, "utf-8").toString("base64")}`;

  const imageResponse = new ImageResponse(
    (
      <div
        style={{
          display: "flex",
          width: "100%",
          height: "100%",
          backgroundColor: "white",
          alignItems: "center",
          justifyContent: "center",
          padding: 40,
        }}
      >
        <img
          src={dataUrl}
          style={{
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
          }}
          width={Math.round(SHARE_PNG_SIZE.w * 0.9)}
          height={Math.round(SHARE_PNG_SIZE.h * 0.7)}
        />
      </div>
    ),
    { width: SHARE_PNG_SIZE.w, height: SHARE_PNG_SIZE.h },
  );

  const cacheControl = cookie
    ? "private, no-store"
    : upstream.headers.get("cache-control") || "public, max-age=300";
  imageResponse.headers.set("Cache-Control", cacheControl);
  return imageResponse;
}
