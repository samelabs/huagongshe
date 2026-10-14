import { NextRequest, NextResponse } from "next/server";
import { ImageResponse } from "next/og";

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { id } = await context.params;
  if (!/^\d+$/.test(id)) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }

  const { searchParams } = new URL(request.url);
  const isSquare = searchParams.get("square") === "1" || searchParams.get("s") === "1";
  const reqW = Number(searchParams.get("w")) || 0;
  const reqH = Number(searchParams.get("h")) || 0;

  const width = isSquare || (reqW > 0 && reqW === reqH) ? (reqW || 800) : (reqW || 1200);
  const height = isSquare || (reqW > 0 && reqW === reqH) ? (reqH || 800) : (reqH || 630);

  const cookie = request.headers.get("cookie");

  let upstream: Response;
  try {
    upstream = await fetch(`${API_ORIGIN}/api/reactions/${id}/svg?w=1600&h=400`, {
      cache: "no-store",
      headers: {
        accept: "image/svg+xml",
        ...(cookie ? { cookie } : {}),
      },
    });
  } catch {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }

  if (upstream.status !== 200) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }

  const svgText = await upstream.text();
  const b64 = Buffer.from(svgText, "utf-8").toString("base64");
  const dataUrl = `data:image/svg+xml;base64,${b64}`;

  // 反应方程式图像容器：纯白底居中留白
  const imgWidth = Math.round(width * 0.9);
  const imgHeight = Math.round(height * 0.7);

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
          width={imgWidth}
          height={imgHeight}
        />
      </div>
    ),
    {
      width,
      height,
    },
  );

  const cacheControl = cookie
    ? "private, no-store"
    : upstream.headers.get("cache-control") || "public, max-age=300";

  imageResponse.headers.set("Cache-Control", cacheControl);
  return imageResponse;
}
