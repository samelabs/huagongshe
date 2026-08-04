import type { Metadata } from "next";
import { KdenseSkillsClient } from "./KdenseSkillsClient";
import t from "@/lib/i18n";

export const metadata: Metadata = {
  title: "K-Dense 科学 AI 技能库",
  description:
    "158 个科学 AI Agent 技能（Skills），覆盖化学信息学、生物信息学、机器学习、科研写作等领域。来自 K-Dense-AI/scientific-agent-skills 开源项目，可按需下载使用。",
  alternates: { canonical: "https://huagongshe.com/skills" },
  robots: { index: true, follow: true },
  openGraph: {
    title: "K-Dense 科学 AI 技能库｜化工社",
    description:
      "158 个科学 AI Agent 技能，覆盖化学、生物、ML、科研写作等 12 个领域",
    url: "/skills",
    siteName: t.brand.name,
    locale: "zh_CN",
    type: "website",
  },
};

export default function SkillsPage() {
  return <KdenseSkillsClient />;
}
