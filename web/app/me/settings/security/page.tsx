import type { Metadata } from "next";
import { SecuritySettings } from "@/components/settings/SecuritySettings";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.settings.nav.security };
export default function SecuritySettingsPage() { return <SecuritySettings />; }
