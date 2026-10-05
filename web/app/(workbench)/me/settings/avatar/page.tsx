import type { Metadata } from "next";
import { AvatarSettings } from "@/components/settings/AvatarSettings";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.settings.avatar.title };
}
export default function AvatarSettingsPage() { return <AvatarSettings />; }
