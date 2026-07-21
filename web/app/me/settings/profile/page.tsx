import type { Metadata } from "next";
import { ProfileSettings } from "@/components/settings/ProfileSettings";

export const metadata: Metadata = { title: "公开资料" };
export default function ProfileSettingsPage() { return <ProfileSettings />; }
