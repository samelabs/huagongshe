import { NextRequest } from "next/server";
import { proxyOAuth } from "@/lib/oauthProxy";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  return proxyOAuth(request, "protected-resource-metadata");
}
