import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "Privacy policy for Huagongshe web, API, MCP, OAuth, and plugin integrations.",
};

export default function PrivacyPage() {
  return <article className="content-page guide-page legal-page">
    <header className="page-head guide-hero">
      <p className="page-kicker">Legal</p>
      <h1>Privacy Policy</h1>
      <p>Effective October 6, 2026</p>
    </header>

    <section className="guide-section">
      <h2>Scope and operator</h2>
      <p>Huagongshe is operated by Shandong Shenglan Chemical Technology Co., Ltd. This policy covers huagongshe.com, its HTTP API, MCP server, OAuth authorization flow, and plugin integrations that connect to those services.</p>
    </section>

    <section className="guide-section">
      <h2>Information we process</h2>
      <p>Depending on how you use the service, we process account information such as username, display name, email address, profile or avatar information; authentication and security data such as password hashes, sessions, API-token metadata, OAuth client and grant records, scopes, and security events; user-created content such as saved reactions, reusable skills, and Notes; and chemistry requests such as names, CAS numbers, HCIDs, HRIDs, SMILES, reaction data, and stoichiometry inputs.</p>
      <p>When you use Huagongshe through ChatGPT or another MCP client, Huagongshe receives only the OAuth and tool requests sent to the MCP server. Huagongshe does not request or reconstruct your full chat history.</p>
    </section>

    <section className="guide-section">
      <h2>How we use information</h2>
      <p>We use this information to authenticate accounts, enforce permissions, provide chemical search and data retrieval, render structures, calculate stoichiometry, store user-requested records, operate reusable skills, prevent abuse, investigate failures, and maintain service security and reliability.</p>
      <p>Some chemistry requests may trigger enrichment or identity work against external chemistry data sources. Those requests are limited to chemistry identifiers or structures needed for the requested operation; account profile data is not sent as chemistry lookup data.</p>
    </section>

    <section className="guide-section">
      <h2>Sharing and service providers</h2>
      <p>We may use hosting, network, database, email, security, and operational service providers to run Huagongshe. Chemistry-source providers may receive the identifiers required for enrichment. If you invoke Huagongshe through OpenAI products, OpenAI separately processes your conversation and connection under its own terms and privacy practices.</p>
      <p>Public website pages may load analytics or advertising scripts when those features are enabled in the site configuration. The MCP tool transport itself does not embed browser advertising scripts.</p>
    </section>

    <section className="guide-section">
      <h2>Retention</h2>
      <ul>
        <li>OAuth authorization codes are valid for 5 minutes, access tokens for 1 hour, and refresh tokens for 30 days. OAuth codes and tokens are stored as cryptographic digests rather than plaintext secrets.</li>
        <li>User-created records are retained while they remain in the account or until the user deletes them through an available product control or requests account/data deletion through support.</li>
        <li>OAuth client registrations are retained while the client remains registered or until disabled or removed.</li>
        <li>Operational access and security logs are retained for up to 30 days, except where a longer period is necessary for an active security investigation or required by law.</li>
      </ul>
    </section>

    <section className="guide-section">
      <h2>Your controls</h2>
      <p>You can control the visibility of supported user records, revoke AI Keys, disconnect an OAuth connection from the client that created it, and change your password to invalidate active HGS sessions and user credentials covered by the password-rotation security flow. For account or data deletion requests, contact support.</p>
    </section>

    <section className="guide-section">
      <h2>Security and credentials</h2>
      <p>Do not place passwords, API keys, OAuth tokens, MFA codes, or other authentication secrets into chemistry fields, plugin prompts, public Notes, or public reaction records. Huagongshe validates authorization server-side for protected operations and applies rate and resource controls to expensive operations.</p>
    </section>

    <section className="guide-section">
      <h2>Contact</h2>
      <p>Privacy and data requests: <a className="footer-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
    </section>
  </article>;
}
