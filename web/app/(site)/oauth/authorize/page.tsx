import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { ApiError, apiGet } from "@/lib/api";

export const metadata: Metadata = {
  title: "Connect HGS AIchem",
  robots: { index: false, follow: false },
};

type Inspect = {
  client_id: string;
  client_name: string;
  redirect_uri: string;
  scopes: string[];
  user: { id: number; username: string; display_name: string };
};

const PARAMS = [
  "response_type",
  "client_id",
  "redirect_uri",
  "scope",
  "state",
  "code_challenge",
  "code_challenge_method",
  "resource",
] as const;

function first(value: string | string[] | undefined): string {
  return typeof value === "string" ? value : Array.isArray(value) ? (value[0] ?? "") : "";
}

export default async function OAuthAuthorizePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const params = new URLSearchParams();
  for (const key of PARAMS) {
    const value = first(raw[key]);
    if (value) params.set(key, value);
  }
  const query = params.toString();
  const cookie = (await headers()).get("cookie");

  let inspected: Inspect;
  try {
    inspected = await apiGet<Inspect>(
      `/oauth/authorize/inspect?${query}`,
      cookie ? { cookie } : undefined,
    );
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      redirect(`/login?next=${encodeURIComponent(`/oauth/authorize?${query}`)}`);
    }
    return (
      <div className="auth-page">
        <section className="auth-panel">
          <h1>Invalid authorization request</h1>
          <p>This HGS connection request could not be validated.</p>
        </section>
      </div>
    );
  }

  const labels: Record<string, string> = {
    read: "Read your private HGS reaction and skill context",
    "reaction:write": "Validate and create reaction records",
    "skill:write": "Validate and create private skills",
  };

  return (
    <div className="auth-page">
      <section className="auth-intro">
        <p className="page-kicker">HGS AICHEM</p>
        <h1>Connect your HGS account</h1>
        <p>
          <strong>{inspected.client_name}</strong> is requesting access to your HGS account.
        </p>
        <ul>
          {inspected.scopes.map((scope) => (
            <li key={scope}>{labels[scope] ?? scope}</li>
          ))}
        </ul>
      </section>
      <section className="auth-panel">
        <p>
          Signed in as <strong>{inspected.user.display_name || inspected.user.username}</strong>
        </p>
        <form className="form-stack" method="post" action="/api/oauth/authorize">
          {PARAMS.map((key) => {
            const value = params.get(key);
            return value ? <input key={key} type="hidden" name={key} value={value} /> : null;
          })}
          <button className="button primary" type="submit" name="decision" value="allow">
            Allow connection
          </button>
          <button className="button" type="submit" name="decision" value="deny">
            Deny
          </button>
        </form>
        <p className="field-hint">
          HGS issues its own OAuth access token. Your HGS password is never shared with the client.
        </p>
      </section>
    </div>
  );
}
