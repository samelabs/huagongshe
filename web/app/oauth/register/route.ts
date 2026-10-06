import { NextRequest } from "next/server";
import { proxyOAuth } from "@/lib/oauthProxy";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  return proxyOAuth(request, "register");
}
