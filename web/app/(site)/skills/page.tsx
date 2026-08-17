import type { Metadata } from "next";
import { KdenseSkillsClient } from "./KdenseSkillsClient";

export const metadata: Metadata = {
  title: "开放技能库",
  description:
    "159 个开源科学 AI Agent 技能 —— 覆盖化学、生物、机器学习、科研写作等领域。数据来自 K-Dense-AI/scientific-agent-skills 开源项目与化工社官方技能。",
  alternates: { canonical: "https://huagongshe.com/skills" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "科学 AI 开放技能库｜化工社",
    description: "159 个开源科学 AI Agent 技能，覆盖化学、生物、机器学习等研究领域。",
    url: "/skills",
    siteName: "化工社",
    locale: "zh_CN",
    type: "website",
  },
};

export default function SkillsPage() {
  return <KdenseSkillsClient />;
}
