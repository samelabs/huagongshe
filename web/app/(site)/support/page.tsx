import type { Metadata } from "next";

import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";
import { CopyButton } from "@/components/ui/CopyButton";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

import { buildShareMetadata } from "@/lib/shareMeta";

/**
 * S3 (-A): 法律/支持页正文只有英文权威版。
 * - 英文路径 (/en/support): canonical + 可索引。
 * - 非英文路径: noindex,follow(正文仍是英文, 不宣称存在译文),
 * 不声明语言互备(没有真实对应译文页面)。
 */
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const canonical = "/en/support";
  const shareMeta = buildShareMetadata({
    title: "Support｜Huagongshe",
    description: "Support information for Huagongshe web, API, MCP, OAuth, and plugin connections.",
    path: "/support",
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
      title: "Support",
      description: "Support information for Huagongshe web, API, MCP, OAuth, and plugin connections.",
      alternates: { canonical },
      ...shareMeta,
    };
  }
  return {
    title: "Support",
    description: "Support information for Huagongshe web, API, MCP, OAuth, and plugin connections.",
    alternates: { canonical },
    robots: { index: false, follow: true },
    ...shareMeta,
  };
}

export default async function SupportPage() {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return <PageFrame tier="reading">
    <article lang="en" className="guide-page legal-page">
    <PageHead
      breadcrumb={[
        { label: t.chemical.home, href: withLocale("/", locale) },
        { label: "Support" },
      ]}
      title="Support"
      meta={<p className="legal-meta">Help with accounts, chemistry data, MCP connections, OAuth authorization, and plugin use.</p>}
    />

    <Section title="Contact">
      <p>Email <span className="inline-copy-target"><a className="legal-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a><CopyButton value="mail@huagongshe.com" ariaLabel="Copy email address" /></span>. Include the feature you were using, the relevant HCID or HRID when applicable, and a concise description of the problem. Never send passwords, AI Keys, OAuth access or refresh tokens, MFA codes, or other authentication secrets.</p>
    </Section>

    <Section title="MCP and OAuth">
      <p>The public MCP endpoint is <span className="inline-copy-target"><code>https://huagongshe.com/mcp</code><CopyButton value="https://huagongshe.com/mcp" ariaLabel="Copy MCP endpoint" /></span>. Public tools can be used anonymously. Private records and write actions use account authorization. Compatible MCP clients can use the standard HGS OAuth flow; existing HGS AI Keys remain available for supported manual integrations.</p>
      <p>If an OAuth connection is rejected, reconnect through the client and confirm the requested scope. Huagongshe OAuth scopes in HGS v1.7.0 are <code>read</code>, <code>reaction:write</code>, and <code>skill:write</code>. Notes are not exposed through MCP in this version.</p>
    </Section>

    <Section title="Data corrections">
      <p>For a chemical identity or reaction-data problem, include the HCID/HRID and the conflicting source evidence. Huagongshe intentionally fails closed on ambiguous or conflicting identity evidence rather than silently merging records.</p>
    </Section>

    <Section title="Privacy and account requests">
      <p>Use the same support address for account or data deletion requests and privacy questions. Do not include credentials in the request.</p>
    </Section>
    </article>
  </PageFrame>;
}
