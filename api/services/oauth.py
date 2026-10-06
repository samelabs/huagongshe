"""OAuth 2.1 service for the HGS MCP connection.

Transport-neutral domain:
- DCR public clients (token_endpoint_auth_method=none)
- Authorization Code + PKCE S256
- opaque access/refresh tokens stored only as SHA-256 hashes
- exact resource binding to the canonical /mcp URL
- refresh-token rotation with replay rejection

This service does not authenticate browser sessions and does not know FastAPI.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text

from ..core.config import settings

OAUTH_SCOPES = ("read", "reaction:write", "skill:write")
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)
AUTH_CODE_TTL = timedelta(minutes=5)
PKCE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")


class OAuthError(Exception):
    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error = error
        self.description = description


def issuer_url() -> str:
    return settings.public_base_url.rstrip("/")


def mcp_resource_url() -> str:
    return f"{issuer_url()}/mcp"


def protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": mcp_resource_url(),
        "resource_name": "HGS AIchem MCP",
        "authorization_servers": [issuer_url()],
        "scopes_supported": list(OAUTH_SCOPES),
        "bearer_methods_supported": ["header"],
        "resource_documentation": f"{issuer_url()}/mcp-guide",
    }


def authorization_server_metadata() -> dict[str, Any]:
    base = issuer_url()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/api/oauth/token",
        "registration_endpoint": f"{base}/api/oauth/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": list(OAUTH_SCOPES),
    }


def token_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def pkce_challenge(verifier: str) -> str:
    if not VERIFIER_RE.fullmatch(verifier):
        raise OAuthError("invalid_grant", "code_verifier is invalid.")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def parse_scopes(raw: str | None, *, default_read: bool = True) -> tuple[str, ...]:
    values = [part for part in (raw or "").split() if part]
    if not values and default_read:
        values = ["read"]
    unknown = [scope for scope in values if scope not in OAUTH_SCOPES]
    if unknown:
        raise OAuthError(
            "invalid_scope",
            f"Unsupported OAuth scope: {unknown[0]}.",
        )
    requested = set(values)
    return tuple(scope for scope in OAUTH_SCOPES if scope in requested)


def _validate_redirect_uri(uri: str, *, application_type: str = "web") -> str:
    try:
        parsed = urlparse(uri)
    except ValueError as exc:
        raise OAuthError("invalid_redirect_uri", "redirect_uri is invalid.") from exc
    if (
        not parsed.netloc
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise OAuthError(
            "invalid_redirect_uri",
            "redirect_uri must be absolute and must not contain a fragment or userinfo.",
        )
    if parsed.scheme == "https":
        return uri
    if (
        application_type == "native"
        and parsed.scheme == "http"
        and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        return uri
    raise OAuthError(
        "invalid_redirect_uri",
        "Web clients require HTTPS; native clients may also use localhost loopback HTTP.",
    )


async def register_client(
    db,
    *,
    redirect_uris: list[str],
    client_name: str | None,
    token_endpoint_auth_method: str,
    grant_types: list[str],
    response_types: list[str],
    scope: str | None,
    application_type: str | None = None,
) -> dict[str, Any]:
    if not redirect_uris or len(redirect_uris) > 20:
        raise OAuthError(
            "invalid_client_metadata",
            "redirect_uris must contain between 1 and 20 URLs.",
        )
    app_type = application_type or "web"
    if app_type not in ("web", "native"):
        raise OAuthError(
            "invalid_client_metadata",
            "application_type must be web or native.",
        )
    unique_uris: list[str] = []
    for uri in redirect_uris:
        value = _validate_redirect_uri(str(uri).strip(), application_type=app_type)
        if value not in unique_uris:
            unique_uris.append(value)

    if token_endpoint_auth_method != "none":
        raise OAuthError(
            "invalid_client_metadata",
            "Only token_endpoint_auth_method=none is supported.",
        )
    allowed_grants = {"authorization_code", "refresh_token"}
    grants = list(dict.fromkeys(grant_types or ["authorization_code", "refresh_token"]))
    if not grants or any(value not in allowed_grants for value in grants):
        raise OAuthError("invalid_client_metadata", "Unsupported grant_types.")
    if "authorization_code" not in grants:
        raise OAuthError(
            "invalid_client_metadata",
            "authorization_code grant is required.",
        )
    responses = list(dict.fromkeys(response_types or ["code"]))
    if responses != ["code"]:
        raise OAuthError(
            "invalid_client_metadata",
            "Only response_type=code is supported.",
        )
    # DCR scope is descriptive client metadata, not the end-user grant.
    # Validate it if present, but register the client for the server's stable
    # supported scope set so later tool-level reauthorization can add write
    # scopes without forcing a second client registration.
    if scope:
        parse_scopes(scope, default_read=False)
    scopes = OAUTH_SCOPES
    name = (client_name or "MCP OAuth client").strip()[:120] or "MCP OAuth client"
    client_id = f"hgo_client_{secrets.token_urlsafe(24)}"

    await db.execute(text("""
        INSERT INTO community.oauth_clients(
            client_id,client_name,redirect_uris,token_endpoint_auth_method,
            grant_types,response_types,scopes,application_type
        ) VALUES (
            :client_id,:client_name,CAST(:redirect_uris AS jsonb),
            :token_endpoint_auth_method,:grant_types,:response_types,:scopes,
            :application_type
        )
    """), {
        "client_id": client_id,
        "client_name": name,
        "redirect_uris": json.dumps(unique_uris),
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "grant_types": grants,
        "response_types": responses,
        "scopes": list(scopes),
        "application_type": app_type,
    })
    await db.commit()
    return {
        "client_id": client_id,
        "client_id_issued_at": int(datetime.now(timezone.utc).timestamp()),
        "client_name": name,
        "redirect_uris": unique_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": grants,
        "response_types": responses,
        "scope": " ".join(scopes),
        "application_type": app_type,
    }


async def _load_client(db, client_id: str):
    return (await db.execute(text("""
        SELECT client_id,client_name,redirect_uris,grant_types,response_types,scopes
        FROM community.oauth_clients
        WHERE client_id=:client_id AND disabled_at IS NULL
    """), {"client_id": client_id})).mappings().first()


async def validate_authorization_request(
    db,
    *,
    response_type: str,
    client_id: str,
    redirect_uri: str,
    scope: str | None,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
) -> dict[str, Any]:
    if response_type != "code":
        raise OAuthError("unsupported_response_type", "Only response_type=code is supported.")
    client = await _load_client(db, client_id)
    if client is None:
        raise OAuthError("invalid_request", "Unknown OAuth client.")
    if redirect_uri not in list(client["redirect_uris"] or []):
        raise OAuthError("invalid_request", "redirect_uri is not registered for this client.")
    if resource != mcp_resource_url():
        raise OAuthError("invalid_target", "resource must identify the HGS MCP endpoint.")
    if code_challenge_method != "S256" or not PKCE_RE.fullmatch(code_challenge or ""):
        raise OAuthError("invalid_request", "PKCE S256 code_challenge is required.")
    scopes = parse_scopes(scope)
    allowed = set(client["scopes"] or ())
    if not set(scopes).issubset(allowed):
        raise OAuthError("invalid_scope", "The client is not registered for the requested scope.")
    return {
        "client_id": client["client_id"],
        "client_name": client["client_name"],
        "redirect_uri": redirect_uri,
        "scopes": scopes,
        "resource": resource,
        "code_challenge": code_challenge,
    }


async def create_authorization_code(
    db,
    *,
    user_id: int,
    client_id: str,
    redirect_uri: str,
    scopes: tuple[str, ...],
    code_challenge: str,
    resource: str,
) -> str:
    plain = f"hgo_code_{secrets.token_urlsafe(36)}"
    expires = datetime.now(timezone.utc) + AUTH_CODE_TTL
    await db.execute(text("""
        INSERT INTO community.oauth_authorization_codes(
            code_hash,user_id,client_id,redirect_uri,scopes,
            code_challenge,resource,expires_at
        ) VALUES (
            :code_hash,:user_id,:client_id,:redirect_uri,:scopes,
            :code_challenge,:resource,:expires_at
        )
    """), {
        "code_hash": token_hash(plain),
        "user_id": user_id,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scopes": list(scopes),
        "code_challenge": code_challenge,
        "resource": resource,
        "expires_at": expires,
    })
    await db.commit()
    return plain


async def _issue_tokens(
    db,
    *,
    user_id: int,
    client_id: str,
    scopes: tuple[str, ...],
    resource: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    access = f"hgo_at_{secrets.token_urlsafe(40)}"
    refresh = f"hgo_rt_{secrets.token_urlsafe(48)}"
    access_expires = now + ACCESS_TOKEN_TTL
    refresh_expires = now + REFRESH_TOKEN_TTL

    await db.execute(text("""
        INSERT INTO community.oauth_access_tokens(
            user_id,client_id,token_hash,token_prefix,scopes,issuer,resource,expires_at
        ) VALUES (
            :user_id,:client_id,:token_hash,:token_prefix,:scopes,:issuer,:resource,:expires_at
        )
    """), {
        "user_id": user_id,
        "client_id": client_id,
        "token_hash": token_hash(access),
        "token_prefix": access[:16],
        "scopes": list(scopes),
        "issuer": issuer_url(),
        "resource": resource,
        "expires_at": access_expires,
    })
    await db.execute(text("""
        INSERT INTO community.oauth_refresh_tokens(
            user_id,client_id,token_hash,token_prefix,scopes,issuer,resource,expires_at
        ) VALUES (
            :user_id,:client_id,:token_hash,:token_prefix,:scopes,:issuer,:resource,:expires_at
        )
    """), {
        "user_id": user_id,
        "client_id": client_id,
        "token_hash": token_hash(refresh),
        "token_prefix": refresh[:16],
        "scopes": list(scopes),
        "issuer": issuer_url(),
        "resource": resource,
        "expires_at": refresh_expires,
    })
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": " ".join(scopes),
    }


async def exchange_authorization_code(
    db,
    *,
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str,
) -> dict[str, Any]:
    row = (await db.execute(text("""
        SELECT ac.id,ac.user_id,ac.client_id,ac.redirect_uri,ac.scopes,
               ac.code_challenge,ac.resource,ac.expires_at
        FROM community.oauth_authorization_codes ac
        JOIN community.oauth_clients c
          ON c.client_id=ac.client_id AND c.disabled_at IS NULL
        WHERE ac.code_hash=:code_hash
        FOR UPDATE OF ac
    """), {"code_hash": token_hash(code)})).mappings().first()
    now = datetime.now(timezone.utc)
    if row is None or row["expires_at"] <= now:
        raise OAuthError("invalid_grant", "Authorization code is invalid or expired.")
    if (
        row["client_id"] != client_id
        or row["redirect_uri"] != redirect_uri
        or row["resource"] != resource
        or resource != mcp_resource_url()
    ):
        raise OAuthError("invalid_grant", "Authorization code binding does not match the request.")
    if pkce_challenge(code_verifier) != row["code_challenge"]:
        raise OAuthError("invalid_grant", "PKCE verification failed.")

    active = (await db.execute(text("""
        SELECT 1 FROM community.users
        WHERE id=:user_id AND status='active'
    """), {"user_id": row["user_id"]})).scalar()
    if not active:
        raise OAuthError("invalid_grant", "The HGS user account is not active.")

    await db.execute(text("""
        DELETE FROM community.oauth_authorization_codes WHERE id=:id
    """), {"id": row["id"]})
    result = await _issue_tokens(
        db,
        user_id=int(row["user_id"]),
        client_id=client_id,
        scopes=tuple(row["scopes"] or ()),
        resource=resource,
    )
    await db.commit()
    return result


async def exchange_refresh_token(
    db,
    *,
    refresh_token: str,
    client_id: str,
    resource: str,
    scope: str | None,
) -> dict[str, Any]:
    row = (await db.execute(text("""
        SELECT rt.id,rt.user_id,rt.client_id,rt.scopes,rt.issuer,rt.resource,rt.expires_at
        FROM community.oauth_refresh_tokens rt
        JOIN community.users u ON u.id=rt.user_id AND u.status='active'
        JOIN community.oauth_clients c
          ON c.client_id=rt.client_id AND c.disabled_at IS NULL
        WHERE rt.token_hash=:token_hash AND rt.revoked_at IS NULL
        FOR UPDATE OF rt
    """), {"token_hash": token_hash(refresh_token)})).mappings().first()
    now = datetime.now(timezone.utc)
    if row is None or row["expires_at"] <= now:
        raise OAuthError("invalid_grant", "Refresh token is invalid, expired, or already rotated.")
    if (
        row["client_id"] != client_id
        or row["issuer"] != issuer_url()
        or row["resource"] != resource
        or resource != mcp_resource_url()
    ):
        raise OAuthError("invalid_grant", "Refresh token binding does not match the request.")

    original = tuple(row["scopes"] or ())
    requested = parse_scopes(scope, default_read=False) if scope else original
    if not set(requested).issubset(set(original)):
        raise OAuthError("invalid_scope", "Refresh cannot expand the original scope grant.")

    await db.execute(text("""
        UPDATE community.oauth_refresh_tokens
        SET revoked_at=now()
        WHERE id=:id AND revoked_at IS NULL
    """), {"id": row["id"]})
    result = await _issue_tokens(
        db,
        user_id=int(row["user_id"]),
        client_id=client_id,
        scopes=tuple(requested),
        resource=resource,
    )
    await db.commit()
    return result


async def resolve_access_token(
    db,
    token: str,
    *,
    expected_resource: str,
):
    row = (await db.execute(text("""
        SELECT at.id,at.user_id,at.client_id,at.scopes,at.issuer,at.resource,
               u.username,u.display_name,u.email,u.role,u.avatar_path
        FROM community.oauth_access_tokens at
        JOIN community.users u ON u.id=at.user_id
        JOIN community.oauth_clients c
          ON c.client_id=at.client_id AND c.disabled_at IS NULL
        WHERE at.token_hash=:token_hash
          AND at.revoked_at IS NULL
          AND at.expires_at>now()
          AND at.issuer=:issuer
          AND at.resource=:resource
          AND u.status='active'
    """), {
        "token_hash": token_hash(token),
        "issuer": issuer_url(),
        "resource": expected_resource,
    })).mappings().first()
    if row is None:
        return None
    await db.execute(text("""
        UPDATE community.oauth_access_tokens
        SET last_used_at=now()
        WHERE id=:id
          AND (last_used_at IS NULL OR last_used_at<now()-interval '5 minutes')
    """), {"id": row["id"]})
    await db.commit()
    return row
