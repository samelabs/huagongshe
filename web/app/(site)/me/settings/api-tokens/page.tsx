import type { Metadata } from "next";
import { ApiTokenSettings } from "@/components/settings/ApiTokenSettings";
import t from "@/lib/i18n";

export const metadata: Metadata = { title: t.settings.ai.title };
export default function ApiTokenSettingsPage() { return <ApiTokenSettings />; }
