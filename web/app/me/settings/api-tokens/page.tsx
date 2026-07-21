import type { Metadata } from "next";
import { ApiTokenSettings } from "@/components/settings/ApiTokenSettings";

export const metadata: Metadata = { title: "API Token" };
export default function ApiTokenSettingsPage() { return <ApiTokenSettings />; }
