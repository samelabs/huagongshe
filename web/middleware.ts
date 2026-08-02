import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// 检测session cookie存在性，通过header传递给SSR
// 避免layout层读cookie导致全站force-dynamic
export function middleware(request: NextRequest) {
  const res = NextResponse.next();
  const session = request.cookies.get("hgs_session");
  if (session) res.headers.set("x-has-session", "1");
  return res;
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon|icon|logo|llms|skills|robots|.*\\.svg|.*\\.png).*)"],
};
