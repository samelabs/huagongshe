-- HGS v1.7.0 MCP OAuth 2.1 domain.
-- Opaque credentials are stored only as SHA-256 hashes.

CREATE TABLE IF NOT EXISTS community.oauth_clients (
    client_id text PRIMARY KEY,
    client_name text NOT NULL,
    redirect_uris jsonb NOT NULL,
    token_endpoint_auth_method text NOT NULL DEFAULT 'none',
    grant_types text[] NOT NULL DEFAULT ARRAY['authorization_code','refresh_token']::text[],
    response_types text[] NOT NULL DEFAULT ARRAY['code']::text[],
    scopes text[] NOT NULL DEFAULT ARRAY['read','reaction:write','skill:write']::text[],
    application_type text NOT NULL DEFAULT 'web',
    created_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz,
    CONSTRAINT oauth_clients_auth_method_check
      CHECK (token_endpoint_auth_method='none'),
    CONSTRAINT oauth_clients_scopes_check
      CHECK (scopes <@ ARRAY['read','reaction:write','skill:write']::text[]),
    CONSTRAINT oauth_clients_application_type_check
      CHECK (application_type IN ('web','native'))
);

CREATE TABLE IF NOT EXISTS community.oauth_authorization_codes (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code_hash bytea NOT NULL UNIQUE,
    user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES community.oauth_clients(client_id) ON DELETE CASCADE,
    redirect_uri text NOT NULL,
    scopes text[] NOT NULL,
    code_challenge text NOT NULL,
    resource text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    CONSTRAINT oauth_authorization_codes_scopes_check
      CHECK (scopes <@ ARRAY['read','reaction:write','skill:write']::text[])
);
CREATE INDEX IF NOT EXISTS oauth_authorization_codes_expiry_idx
    ON community.oauth_authorization_codes(expires_at);

CREATE TABLE IF NOT EXISTS community.oauth_access_tokens (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES community.oauth_clients(client_id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    token_prefix text NOT NULL,
    scopes text[] NOT NULL,
    issuer text NOT NULL,
    resource text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_used_at timestamptz,
    revoked_at timestamptz,
    CONSTRAINT oauth_access_tokens_scopes_check
      CHECK (scopes <@ ARRAY['read','reaction:write','skill:write']::text[])
);
CREATE INDEX IF NOT EXISTS oauth_access_tokens_user_idx
    ON community.oauth_access_tokens(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS oauth_access_tokens_expiry_idx
    ON community.oauth_access_tokens(expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS community.oauth_refresh_tokens (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id bigint NOT NULL REFERENCES community.users(id) ON DELETE CASCADE,
    client_id text NOT NULL REFERENCES community.oauth_clients(client_id) ON DELETE CASCADE,
    token_hash bytea NOT NULL UNIQUE,
    token_prefix text NOT NULL,
    scopes text[] NOT NULL,
    issuer text NOT NULL,
    resource text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    CONSTRAINT oauth_refresh_tokens_scopes_check
      CHECK (scopes <@ ARRAY['read','reaction:write','skill:write']::text[])
);
CREATE INDEX IF NOT EXISTS oauth_refresh_tokens_user_idx
    ON community.oauth_refresh_tokens(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS oauth_refresh_tokens_expiry_idx
    ON community.oauth_refresh_tokens(expires_at)
    WHERE revoked_at IS NULL;
