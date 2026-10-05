import type { Metadata } from "next";
import { SecuritySettings } from "@/components/settings/SecuritySettings";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.settings.nav.security };
}
export default function SecuritySettingsPage() { return <SecuritySettings />; }
