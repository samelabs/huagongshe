import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Terms for using Huagongshe web, API, MCP, OAuth, and plugin integrations.",
};

export default function TermsPage() {
  return <article className="content-page guide-page legal-page">
    <header className="page-head guide-hero">
      <p className="page-kicker">Legal</p>
      <h1>Terms of Service</h1>
      <p>Effective October 6, 2026</p>
    </header>

    <section className="guide-section">
      <h2>Service</h2>
      <p>Huagongshe provides chemical information, reaction records, structure rendering, stoichiometry tools, reusable skills, user workspaces, APIs, and MCP access. The service is operated by Shandong Shenglan Chemical Technology Co., Ltd.</p>
    </section>

    <section className="guide-section">
      <h2>Chemical information</h2>
      <p>Huagongshe aggregates and processes chemical data from multiple sources and user records. Data may be incomplete, conflicting, stale, or unsuitable for a particular experiment or regulatory decision. You are responsible for independently verifying structures, identities, reaction conditions, yields, safety information, legal restrictions, and process suitability before relying on them.</p>
      <p>Huagongshe is not a substitute for professional laboratory safety review, regulatory advice, medical advice, or process-safety engineering.</p>
    </section>

    <section className="guide-section">
      <h2>Accounts and authorization</h2>
      <p>You are responsible for activity performed through your account and credentials. Keep passwords, AI Keys, OAuth tokens, and other secrets confidential. Do not share credentials through prompts, public records, source code, or logs.</p>
      <p>When an AI client is authorized to act for your account, protected tool calls are treated as actions by that authorized account. Review write actions before confirming them and grant only the scopes needed for your intended use.</p>
    </section>

    <section className="guide-section">
      <h2>User content</h2>
      <p>You retain responsibility for reaction records, skills, Notes, and other content you submit. You grant Huagongshe the limited rights needed to store, process, display, and transmit that content according to its visibility and the operations you request.</p>
      <p>Do not submit content that you do not have the right to use or that violates applicable law or another person&apos;s rights.</p>
    </section>

    <section className="guide-section">
      <h2>Acceptable use</h2>
      <p>Do not attempt to bypass authentication, authorization, rate limits, resource limits, moderation controls, or technical safeguards; interfere with other users or service operation; upload malicious skill packages; or use the service for unlawful activity.</p>
    </section>

    <section className="guide-section">
      <h2>Third-party sources and clients</h2>
      <p>Huagongshe may rely on third-party chemistry sources and infrastructure. MCP clients and AI platforms, including OpenAI products, operate under their own terms. Availability or behavior of those external services may affect a Huagongshe workflow.</p>
    </section>

    <section className="guide-section">
      <h2>Availability and changes</h2>
      <p>We may change, suspend, limit, or discontinue service features to maintain security, reliability, legal compliance, or product quality. Published API and MCP contracts may carry specific compatibility commitments documented by Huagongshe; other interfaces may evolve.</p>
    </section>

    <section className="guide-section">
      <h2>Disclaimer and liability</h2>
      <p>The service is provided on an as-available basis. To the extent permitted by applicable law, Huagongshe and its operator disclaim warranties not expressly stated here and are not responsible for losses caused by unverified chemical data, user-supplied content, misuse of credentials, or decisions made without appropriate professional review.</p>
    </section>

    <section className="guide-section">
      <h2>Contact</h2>
      <p>Questions about these terms: <a className="footer-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
    </section>
  </article>;
}
