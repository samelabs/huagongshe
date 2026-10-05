import type { Metadata } from "next";
import { ApiTokenSettings } from "@/components/settings/ApiTokenSettings";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.settings.ai.title };
}
export default function ApiTokenSettingsPage() { return <ApiTokenSettings />; }
