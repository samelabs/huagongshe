import type { Metadata } from "next";

import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

import { buildShareMetadata } from "@/lib/shareMeta";

/**
 * S3 (-A): 法律/支持页正文只有英文权威版。
 * - 英文路径 (/en/terms): canonical + 可索引。
 * - 非英文路径: noindex,follow(正文仍是英文, 不宣称存在译文),
 * 不声明语言互备(没有真实对应译文页面)。
 */
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const canonical = "/en/terms";
  const shareMeta = buildShareMetadata({
    title: "Terms of Service｜Huagongshe",
    description: "Terms for using Huagongshe web, API, MCP, OAuth, and plugin integrations.",
    path: "/terms",
    locale,
    siteName: "Huagongshe",
    ogImage: {
      url: "/og.png",
      width: 1200,
      height: 630,
      alt: "Huagongshe",
    },
    twitterCard: "summary_large_image",
  });
  if (locale === "en") {
    return {
      title: "Terms of Service",
      description: "Terms for using Huagongshe web, API, MCP, OAuth, and plugin integrations.",
      alternates: { canonical },
      ...shareMeta,
    };
  }
  return {
    title: "Terms of Service",
    description: "Terms for using Huagongshe web, API, MCP, OAuth, and plugin integrations.",
    alternates: { canonical },
    robots: { index: false, follow: true },
    ...shareMeta,
  };
}

export default async function TermsPage() {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return <PageFrame tier="reading">
    <article lang="en" className="guide-page legal-page">
    <PageHead
      breadcrumb={[
        { label: t.chemical.home, href: withLocale("/", locale) },
        { label: "Terms of Service" },
      ]}
      title="Terms of Service"
      meta={<p className="legal-meta">Effective October 6, 2026</p>}
    />

    <Section title="Service">
      <p>Huagongshe provides chemical information, reaction records, structure rendering, stoichiometry tools, reusable skills, user workspaces, APIs, and MCP access. The service is operated by Shandong Shenglan Chemical Technology Co., Ltd.</p>
    </Section>

    <Section title="Chemical information">
      <p>Huagongshe aggregates and processes chemical data from multiple sources and user records. Data may be incomplete, conflicting, stale, or unsuitable for a particular experiment or regulatory decision. You are responsible for independently verifying structures, identities, reaction conditions, yields, safety information, legal restrictions, and process suitability before relying on them.</p>
      <p>Huagongshe is not a substitute for professional laboratory safety review, regulatory advice, medical advice, or process-safety engineering.</p>
    </Section>

    <Section title="Accounts and authorization">
      <p>You are responsible for activity performed through your account and credentials. Keep passwords, AI Keys, OAuth tokens, and other secrets confidential. Do not share credentials through prompts, public records, source code, or logs.</p>
      <p>When an AI client is authorized to act for your account, protected tool calls are treated as actions by that authorized account. Review write actions before confirming them and grant only the scopes needed for your intended use.</p>
    </Section>

    <Section title="User content">
      <p>You retain responsibility for reaction records, skills, Notes, and other content you submit. You grant Huagongshe the limited rights needed to store, process, display, and transmit that content according to its visibility and the operations you request.</p>
      <p>Do not submit content that you do not have the right to use or that violates applicable law or another person&apos;s rights.</p>
    </Section>

    <Section title="Acceptable use">
      <p>Do not attempt to bypass authentication, authorization, rate limits, resource limits, moderation controls, or technical safeguards; interfere with other users or service operation; upload malicious skill packages; or use the service for unlawful activity.</p>
    </Section>

    <Section title="Third-party sources and clients">
      <p>Huagongshe may rely on third-party chemistry sources and infrastructure. MCP clients and AI platforms, including OpenAI products, operate under their own terms. Availability or behavior of those external services may affect a Huagongshe workflow.</p>
    </Section>

    <Section title="Availability and changes">
      <p>We may change, suspend, limit, or discontinue service features to maintain security, reliability, legal compliance, or product quality. Published API and MCP contracts may carry specific compatibility commitments documented by Huagongshe; other interfaces may evolve.</p>
    </Section>

    <Section title="Disclaimer and liability">
      <p>The service is provided on an as-available basis. To the extent permitted by applicable law, Huagongshe and its operator disclaim warranties not expressly stated here and are not responsible for losses caused by unverified chemical data, user-supplied content, misuse of credentials, or decisions made without appropriate professional review.</p>
    </Section>

    <Section title="Contact">
      <p>Questions about these terms: <a className="legal-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
    </Section>
    </article>
  </PageFrame>;
}
