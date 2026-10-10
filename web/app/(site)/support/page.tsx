import type { Metadata } from "next";

import { CopyButton } from "@/components/ui/CopyButton";
import { getRequestLocale } from "@/lib/serverI18n";

/**
 * S3 (G1.5-A): 法律/支持页正文只有英文权威版。
 * - 英文路径 (/en/support): canonical + 可索引。
 * - 非英文路径: noindex,follow(正文仍是英文, 不宣称存在译文),
 *   不声明语言互备(没有真实对应译文页面)。
 */
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  const canonical = "/en/support";
  if (locale === "en") {
    return {
      title: "Support",
      description: "Support information for Huagongshe web, API, MCP, OAuth, and plugin connections.",
      alternates: { canonical },
    };
  }
  return {
    title: "Support",
    description: "Support information for Huagongshe web, API, MCP, OAuth, and plugin connections.",
    alternates: { canonical },
    robots: { index: false, follow: true },
  };
}

export default function SupportPage() {
  return <article lang="en" className="content-page guide-page legal-page">
    <header className="page-head guide-hero">
      <h1>Support</h1>
      <p className="legal-meta">Help with accounts, chemistry data, MCP connections, OAuth authorization, and plugin use.</p>
    </header>

    <section className="guide-section">
      <h2>Contact</h2>
      <p>Email <a className="footer-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a> <CopyButton value="mail@huagongshe.com" ariaLabel="Copy email address" />. Include the feature you were using, the relevant HCID or HRID when applicable, and a concise description of the problem. Never send passwords, AI Keys, OAuth access or refresh tokens, MFA codes, or other authentication secrets.</p>
    </section>

    <section className="guide-section">
      <h2>MCP and OAuth</h2>
      <p>The public MCP endpoint is <code>https://huagongshe.com/mcp</code> <CopyButton value="https://huagongshe.com/mcp" ariaLabel="Copy MCP endpoint" />. Public tools can be used anonymously. Private records and write actions use account authorization. Compatible MCP clients can use the standard HGS OAuth flow; existing HGS AI Keys remain available for supported manual integrations.</p>
      <p>If an OAuth connection is rejected, reconnect through the client and confirm the requested scope. Huagongshe OAuth scopes in HGS v1.7.0 are <code>read</code>, <code>reaction:write</code>, and <code>skill:write</code>. Notes are not exposed through MCP in this version.</p>
    </section>

    <section className="guide-section">
      <h2>Data corrections</h2>
      <p>For a chemical identity or reaction-data problem, include the HCID/HRID and the conflicting source evidence. Huagongshe intentionally fails closed on ambiguous or conflicting identity evidence rather than silently merging records.</p>
    </section>

    <section className="guide-section">
      <h2>Privacy and account requests</h2>
      <p>Use the same support address for account or data deletion requests and privacy questions. Do not include credentials in the request.</p>
    </section>
  </article>;
}
