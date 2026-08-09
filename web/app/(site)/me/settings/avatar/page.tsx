import type { Metadata } from "next";
import { AvatarSettings } from "@/components/settings/AvatarSettings";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.settings.avatar.title };
export default function AvatarSettingsPage() { return <AvatarSettings />; }
