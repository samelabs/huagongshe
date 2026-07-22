import type { Metadata } from "next";
import { ApiTokenSettings } from "@/components/settings/ApiTokenSettings";

export const metadata: Metadata = { title: "AI 授权" };
export default function ApiTokenSettingsPage() { return <ApiTokenSettings />; }
