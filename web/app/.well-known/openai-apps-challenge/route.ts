import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export async function GET() {
  const token = (process.env.HGS_OPENAI_APPS_CHALLENGE ?? "").trim();
  if (!token || token.length > 512 || /[\r\n]/.test(token)) {
    return new NextResponse("Not configured", {
      status: 404,
      headers: {
        "content-type": "text/plain; charset=utf-8",
        "cache-control": "no-store",
      },
    });
  }
  return new NextResponse(token, {
    status: 200,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}
