import type { Metadata } from "next";

import { PageFrame } from "@/components/ui/PageFrame";
import { PageHead } from "@/components/ui/PageHead";
import { Section } from "@/components/ui/Section";
import { getRequestDictionary, getRequestLocale } from "@/lib/serverI18n";
import { withLocale } from "@/lib/localePath";

import { buildShareMetadata } from "@/lib/shareMeta";

/**
 * S3 (-A): 法律/支持页正文只有英文权威版。
 * - 英文路径 (/en/privacy): canonical + 可索引。
 * - 非英文路径: noindex,follow(正文仍是英文, 不宣称存在译文),
 * 不声明语言互备(没有真实对应译文页面)。
 */
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const canonical = "/en/privacy";
  const shareMeta = buildShareMetadata({
    title: "Privacy Policy｜Huagongshe",
    description: "Privacy policy for Huagongshe web, API, MCP, OAuth, and plugin integrations.",
    path: "/privacy",
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
      title: "Privacy Policy",
      description: "Privacy policy for Huagongshe web, API, MCP, OAuth, and plugin integrations.",
      alternates: { canonical },
      ...shareMeta,
    };
  }
  return {
    title: "Privacy Policy",
    description: "Privacy policy for Huagongshe web, API, MCP, OAuth, and plugin integrations.",
    alternates: { canonical },
    robots: { index: false, follow: true },
    ...shareMeta,
  };
}

export default async function PrivacyPage() {
  const locale = await getRequestLocale();
  const t = await getRequestDictionary();
  return <PageFrame tier="reading">
    <article lang="en" className="guide-page legal-page">
    <PageHead
      breadcrumb={[
        { label: t.chemical.home, href: withLocale("/", locale) },
        { label: "Privacy Policy" },
      ]}
      title="Privacy Policy"
      meta={<p className="legal-meta">Effective October 6, 2026</p>}
    />

    <Section title="Scope and operator">
      <p>Huagongshe is operated by Shandong Shenglan Chemical Technology Co., Ltd. This policy covers huagongshe.com, its MCP server, OAuth authorization flow, and plugin integrations that connect to those services.</p>
    </Section>

    <Section title="Information we process">
      <p>Depending on how you use the service, we process account information such as username, display name, email address, profile or avatar information; authentication and security data such as password hashes, sessions, API-token metadata, OAuth client and grant records, scopes, network/request metadata such as IP address and user agent where processed by service infrastructure, and security events; user-created content such as saved reactions, reusable skills, and Notes; and chemistry requests such as names, CAS numbers, HCIDs, HRIDs, SMILES, reaction data, and stoichiometry inputs.</p>
      <p>When you use Huagongshe through ChatGPT or another MCP client, Huagongshe receives only the OAuth and tool requests sent to the MCP server. Huagongshe does not request or reconstruct your full chat history.</p>
    </Section>

    <Section title="How we use information">
      <p>We use this information to authenticate accounts, enforce permissions, provide chemical search and data retrieval, render structures, calculate stoichiometry, store user-requested records, operate reusable skills, prevent abuse, investigate failures, and maintain service security and reliability.</p>
      <p>Some chemistry requests may trigger enrichment or identity work against external chemistry data sources. Those requests are limited to chemistry identifiers or structures needed for the requested operation; account profile data is not sent as chemistry lookup data.</p>
    </Section>

    <Section title="Sharing and service providers">
      <p>We may use hosting, network, database, email, security, and operational service providers to run Huagongshe. Chemistry-source providers may receive the identifiers required for enrichment. If you invoke Huagongshe through OpenAI products, OpenAI separately processes your conversation and connection under its own terms and privacy practices.</p>
      <p>Public website pages may load analytics or advertising scripts when those features are enabled in the site configuration; those providers may receive browser, device, or network metadata needed to deliver their service. The MCP tool transport itself does not embed browser advertising scripts.</p>
    </Section>

    <Section title="Retention">
      <ul>
        <li>OAuth authorization codes are valid for 5 minutes, access tokens for 1 hour, and refresh tokens for 30 days. OAuth codes and tokens are stored as cryptographic digests rather than plaintext secrets.</li>
        <li>User-created records are retained while they remain in the account or until the user deletes them through an available product control or requests account/data deletion through support.</li>
        <li>OAuth client registrations are retained while the client remains registered or until disabled or removed.</li>
        <li>Operational access and security logs are retained for up to 30 days, except where a longer period is necessary for an active security investigation or required by law.</li>
      </ul>
    </Section>

    <Section title="Your controls">
      <p>You can control the visibility of supported user records and revoke AI Keys. Disconnecting an OAuth connection in the client stops that client from using the connection; changing your HGS password also revokes active HGS sessions, AI Keys, and OAuth grants covered by the password-rotation security flow. For account or data deletion requests, contact support.</p>
    </Section>

    <Section title="Security and credentials">
      <p>Do not place passwords, API keys, OAuth tokens, MFA codes, or other authentication secrets into chemistry fields, plugin prompts, public Notes, or public reaction records. Huagongshe validates authorization server-side for protected operations and applies rate and resource controls to expensive operations.</p>
    </Section>

    <Section title="Contact">
      <p>Privacy and data requests: <a className="legal-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
    </Section>
    </article>
  </PageFrame>;
}
