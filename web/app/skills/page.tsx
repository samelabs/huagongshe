import type { Metadata } from "next";
import { KdenseSkillsClient } from "./KdenseSkillsClient";

export const metadata: Metadata = {
  title: "Open Skills",
  description:
    "158 open-source AI agent skills for scientific research — chemistry, biology, machine learning, academic writing and more. From K-Dense-AI/scientific-agent-skills.",
  alternates: { canonical: "https://huagongshe.com/skills" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "Open Skills｜化工社",
    description:
      "158 open-source scientific AI agent skills across 12 domains.",
    url: "/skills",
    siteName: "化工社",
    locale: "zh_CN",
    type: "website",
  },
};

export default function SkillsPage() {
  return <KdenseSkillsClient />;
}
