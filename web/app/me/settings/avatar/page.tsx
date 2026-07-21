import type { Metadata } from "next";
import { AvatarSettings } from "@/components/settings/AvatarSettings";

export const metadata: Metadata = { title: "头像" };
export default function AvatarSettingsPage() { return <AvatarSettings />; }
