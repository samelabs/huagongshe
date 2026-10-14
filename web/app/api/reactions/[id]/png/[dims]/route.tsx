import { NextRequest, NextResponse } from "next/server";
import { ImageResponse } from "next/og";
import { ALLOWED_REACTION_SHARE_PNG_DIMS } from "@/lib/molSizes";

const API_ORIGIN = process.env.API_ORIGIN_INTERNAL || "http://127.0.0.1:8000";

type RouteContext = { params: Promise<{ id: string; dims: string }> };

export async function GET(request: NextRequest, context: RouteContext) {
  const { id, dims } = await context.params;
  const match = dims.match(/^(\d+x\d+)\.png$/);
  if (!/^\d+$/.test(id) || !match || !ALLOWED_REACTION_SHARE_PNG_DIMS.has(match[1])) {
    return NextResponse.json({ detail: "Not Found" }, { status: 404 });
  }

  const [wStr, hStr] = match[1].split("x");
  const width = Number(wStr);
  const height = Number(hStr);

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
