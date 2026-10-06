import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "HGS Terms of Service",
  robots: { index: true, follow: true },
};

export default function Page() {
  return (
    <div className="content-page guide-page">
      <header className="page-head">
        <p className="page-kicker">TERMS</p>
        <h1>HGS Terms of Service</h1>
      </header>
      
      <section className="guide-section">
        <p><strong>Effective date: October 6, 2026.</strong></p>
        <p>These terms govern use of HGS AIchem, huagongshe.com, its APIs, and its MCP tools operated by Shandong Shenglan Chemical Technology Co., Ltd. By using the service, you agree to use it lawfully and within the permissions granted to your account.</p>
      </section>
      <section className="guide-section">
        <h2>Chemical information</h2>
        <p>HGS aggregates and organizes chemical and reaction information from multiple sources and user records. Data may be incomplete, source-specific, delayed, or inconsistent. HGS output is informational and must not replace laboratory verification, safety review, regulatory assessment, quality control, or professional judgment.</p>
      </section>
      <section className="guide-section">
        <h2>Accounts and connected clients</h2>
        <p>You are responsible for your HGS account and for protecting credentials. Do not provide passwords, API keys, OAuth tokens, or other authentication secrets in ordinary tool inputs or support messages. A connected AI client may act only with the scopes and permissions granted to that connection.</p>
      </section>
      <section className="guide-section">
        <h2>User content and permissions</h2>
        <p>You retain responsibility for records and files you submit. You must have the right to provide that content and must not use HGS to obtain or disclose another user's private information. Public records may be displayed through HGS public surfaces according to their visibility settings.</p>
      </section>
      <section className="guide-section">
        <h2>Acceptable use</h2>
        <p>Do not misuse HGS to bypass access controls, disrupt the service, falsify provenance, impersonate others, introduce malicious content, or perform unlawful activity. Automated access must respect HGS authentication, rate limits, and tool contracts.</p>
      </section>
      <section className="guide-section">
        <h2>Availability and changes</h2>
        <p>We may maintain, modify, limit, suspend, or discontinue service features when necessary for reliability, security, legal compliance, or product development. We may update these terms and will publish the current version on this page.</p>
      </section>
      <section className="guide-section">
        <h2>Warranty and liability</h2>
        <p>The service is provided on an as-available basis to the extent permitted by applicable law. HGS does not warrant that every chemical record, reaction condition, identifier, rendering, calculation, or external source is complete or error-free. Users remain responsible for decisions and actions based on service output.</p>
      </section>
      <section className="guide-section">
        <h2>Contact</h2>
        <p>Questions about these terms: <a className="footer-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
      </section>
    </div>
  );
}
