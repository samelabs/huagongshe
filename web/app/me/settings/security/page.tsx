import type { Metadata } from "next";
import { SecuritySettings } from "@/components/settings/SecuritySettings";

export const metadata: Metadata = { title: "密码安全" };
export default function SecuritySettingsPage() { return <SecuritySettings />; }
