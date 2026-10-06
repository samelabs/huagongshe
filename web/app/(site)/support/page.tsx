import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "HGS Support",
  robots: { index: true, follow: true },
};

export default function Page() {
  return (
    <div className="content-page guide-page">
      <header className="page-head">
        <p className="page-kicker">SUPPORT</p>
        <h1>HGS Support</h1>
      </header>
      
      <section className="guide-section">
        <p>For help with HGS AIchem, account access, MCP connections, OAuth authorization, chemical or reaction data display, and tool behavior, contact <a className="footer-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
        <p>Include the HGS username, affected HCID/HRID when relevant, the tool or page involved, and a concise description of the issue. Do not send passwords, API keys, OAuth access/refresh tokens, or other authentication secrets.</p>
      </section>
      <section className="guide-section">
        <h2>Plugin connection issues</h2>
        <p>If an AI client asks you to reconnect HGS, complete the HGS authorization flow again. HGS public chemistry tools can work anonymously; private account context and write operations require the permissions shown during authorization.</p>
      </section>
      <section className="guide-section">
        <h2>Data and privacy requests</h2>
        <p>Use the same support address for access, correction, deletion, privacy, or security requests. We may need to verify account ownership before changing or disclosing account data.</p>
      </section>
    </div>
  );
}
