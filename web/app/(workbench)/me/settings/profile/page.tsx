import type { Metadata } from "next";
import { ProfileSettings } from "@/components/settings/ProfileSettings";
import { getRequestDictionary } from "@/lib/serverI18n";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getRequestDictionary();
  return { title: t.settings.profile.title };
}
export default function ProfileSettingsPage() { return <ProfileSettings />; }
