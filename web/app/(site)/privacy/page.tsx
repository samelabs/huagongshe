import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "HGS Privacy Policy",
  robots: { index: true, follow: true },
};

export default function Page() {
  return (
    <div className="content-page guide-page">
      <header className="page-head">
        <p className="page-kicker">PRIVACY</p>
        <h1>HGS Privacy Policy</h1>
      </header>
      
      <section className="guide-section">
        <p><strong>Effective date: October 6, 2026.</strong></p>
        <p>HGS AIchem and huagongshe.com are operated by Shandong Shenglan Chemical Technology Co., Ltd. This policy describes how HGS handles personal data for the website, account features, API credentials, and the HGS MCP connection used by compatible AI clients.</p>
      </section>
      <section className="guide-section">
        <h2>Data we process</h2>
        <p>When you create an HGS account, we process account and profile information such as username, email address, display name, and profile fields you choose to provide. When you use HGS features, we process the reaction records, skills, notes, and other content you intentionally submit.</p>
        <p>For OAuth-connected MCP use, HGS processes the OAuth client identifier, granted scopes, authorization and token records, expiration and revocation state, and limited usage state needed to authenticate requests. Raw OAuth access and refresh tokens are not stored after issuance; HGS stores cryptographic hashes for verification.</p>
        <p>HGS also processes limited technical and security signals needed to operate the service, such as request timing, rate-limit state, and network information used to protect anonymous endpoints. HGS receives only the arguments a connected client sends to an HGS tool; it does not receive your full ChatGPT conversation unless that content is explicitly included in a tool request.</p>
      </section>
      <section className="guide-section">
        <h2>How we use data</h2>
        <p>We use this data to authenticate accounts, return chemical and reaction information, save user-requested records, enforce visibility and permissions, prevent abuse, maintain service reliability, and respond to support or legal requests. We do not use OAuth credentials as a separate advertising profile.</p>
      </section>
      <section className="guide-section">
        <h2>Sharing and public content</h2>
        <p>HGS sends tool results to the connected client that made the request, including OpenAI products when you connect HGS there. We may use infrastructure and service providers that process data on our behalf, and we may disclose information where required by law or necessary to protect users and the service.</p>
        <p>Records you explicitly publish as public may be visible to other HGS users and visitors. Private records remain subject to HGS access controls.</p>
      </section>
      <section className="guide-section">
        <h2>Retention and security</h2>
        <p>Account and user-created records are retained while needed to provide the service or until they are deleted through available product controls or a verified deletion request. OAuth authorization codes are valid for 5 minutes, access tokens for 1 hour, and refresh tokens for 30 days unless revoked earlier. Expired or revoked authorization records may be retained for a limited security and audit period before operational deletion.</p>
        <p>HGS uses hashed session, API-authorization, and OAuth credential checks, scoped permissions, resource binding, and other technical controls. No online service can guarantee absolute security.</p>
      </section>
      <section className="guide-section">
        <h2>Your choices</h2>
        <p>You can control public/private visibility where the product provides it, revoke HGS API credentials, disconnect HGS from the client you connected, and contact us to request access, correction, or deletion of personal data where applicable. Changing your HGS password invalidates active HGS sessions and issued API/OAuth credentials.</p>
      </section>
      <section className="guide-section">
        <h2>Contact</h2>
        <p>Privacy and data requests: <a className="footer-link" href="mailto:mail@huagongshe.com">mail@huagongshe.com</a>.</p>
      </section>
    </div>
  );
}
