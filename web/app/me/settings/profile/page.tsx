import type { Metadata } from "next";
import { ProfileSettings } from "@/components/settings/ProfileSettings";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.settings.profile.title };
export default function ProfileSettingsPage() { return <ProfileSettings />; }
