import { apiGet } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  const metadata = await apiGet<Record<string, unknown>>("/oauth/authorization-server-metadata");
  return Response.json(metadata, {
    headers: { "Cache-Control": "public, max-age=300" },
  });
}
