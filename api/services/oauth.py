"""OAuth 2.1 domain for MCP account linking.

Opaque credentials are stored only as SHA-256 digests. The OAuth access-token
family is intentionally separate from existing hgs_ API keys and is resolved
only by the MCP adapter in v1.7.0.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text

from ..core.config import settings

SCOPES = ("read", "reaction:write", "skill:write")
PKCE_CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
PKCE_VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
ACCESS_TOKEN_SECONDS = 3600
REFRESH_TOKEN_DAYS = 30
AUTH_CODE_SECONDS = 300
AUTH_REQUEST_SECONDS = 600


class OAuthProtocolError(Exception):
    def __init__(self, error: str, description: str, *, status_code: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def issuer_url() -> str:
    return settings.public_base_url.rstrip("/")


def mcp_resource_url() -> str:
    return f"{issuer_url()}/mcp"


def protected_resource_metadata() -> dict[str, Any]:
    return {
        "resource": mcp_resource_url(),
        "authorization_servers": [issuer_url()],
        "scopes_supported": list(SCOPES),
        "resource_documentation": f"{issuer_url()}/mcp-guide",
    }


def authorization_server_metadata() -> dict[str, Any]:
    base = issuer_url()
    return {
        "issuer": base,
        "authorization_endpoint": f"{base}/oauth/authorize",
        "token_endpoint": f"{base}/oauth/token",
        "registration_endpoint": f"{base}/oauth/register",
        "token_endpoint_auth_methods_supported": ["none"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": list(SCOPES),
    }


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def _plain(prefix: str, nbytes: int = 32) -> str:
    return f"{prefix}{secrets.token_urlsafe(nbytes)}"


def _scope_tuple(raw: str | None, *, default_read: bool = False) -> tuple[str, ...]:
    values = [part for part in (raw or "").split() if part]
    if not values and default_read:
        values = ["read"]
    if len(values) != len(set(values)):
        values = list(dict.fromkeys(values))
    invalid = [scope for scope in values if scope not in SCOPES]
    if invalid:
        raise OAuthProtocolError(
            "invalid_scope",
            f"Unsupported OAuth scope: {invalid[0]}",
        )
    return tuple(values)


def _valid_redirect_uri(value: str) -> bool:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.fragment or not parsed.scheme or not parsed.netloc:
        return False
    if parsed.scheme == "https":
        return True
    if parsed.scheme == "http" and parsed.hostname in {
        "localhost", "127.0.0.1", "::1"
    }:
        return True
    return False


def _redirect_with(uri: str, **values: str | None) -> str:
    parsed = urlsplit(uri)
    query = list(parse_qsl(parsed.query, keep_blank_values=True))
    query.extend((key, value) for key, value in values.items() if value is not None)
    return urlunsplit((
        parsed.scheme, parsed.netloc, parsed.path,
        urlencode(query), parsed.fragment,
    ))


def _verify_pkce(verifier: str, challenge: str) -> bool:
    if not PKCE_VERIFIER_RE.fullmatch(verifier):
        return False
    actual = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return hmac.compare_digest(actual, challenge)


async def register_client(
    db,
    *,
    redirect_uris: list[str],
    client_name: str | None,
    token_endpoint_auth_method: str | None,
    grant_types: list[str] | None,
    response_types: list[str] | None,
    application_type: str | None,
) -> dict[str, Any]:
    if not redirect_uris or len(redirect_uris) > 10:
        raise OAuthProtocolError(
            "invalid_client_metadata", "redirect_uris must contain 1-10 entries."
        )
    if any(not _valid_redirect_uri(uri) for uri in redirect_uris):
        raise OAuthProtocolError(
            "invalid_redirect_uri",
            "Every redirect URI must use HTTPS, except localhost loopback URIs.",
        )
    if token_endpoint_auth_method not in (None, "none"):
        raise OAuthProtocolError(
            "invalid_client_metadata",
            "This authorization server registers public clients only.",
        )
    grants = grant_types or ["authorization_code", "refresh_token"]
    if any(value not in ("authorization_code", "refresh_token") for value in grants):
        raise OAuthProtocolError(
            "invalid_client_metadata", "Unsupported grant_types value."
        )
    responses = response_types or ["code"]
    if responses != ["code"]:
        raise OAuthProtocolError(
            "invalid_client_metadata", "Only response_type=code is supported."
        )
    if application_type not in (None, "web", "native"):
        raise OAuthProtocolError(
            "invalid_client_metadata", "application_type must be web or native."
        )

    client_id = _plain("hgo_client_", 24)
    await db.execute(text("""
        INSERT INTO community.oauth_clients(
            client_id,client_name,redirect_uris,token_endpoint_auth_method,
            grant_types,response_types,application_type
        ) VALUES (
            :client_id,:client_name,:redirect_uris,'none',
            :grant_types,:response_types,:application_type
        )
    """), {
        "client_id": client_id,
        "client_name": (client_name or "MCP client")[:160],
        "redirect_uris": redirect_uris,
        "grant_types": grants,
        "response_types": responses,
        "application_type": application_type or "web",
    })
    await db.commit()
    return {
        "client_id": client_id,
        "client_id_issued_at": int(datetime.now(timezone.utc).timestamp()),
        "client_name": (client_name or "MCP client")[:160],
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
        "grant_types": grants,
        "response_types": responses,
        "application_type": application_type or "web",
    }


async def _load_client(db, client_id: str):
    return (await db.execute(text("""
        SELECT client_id,client_name,redirect_uris
        FROM community.oauth_clients
        WHERE client_id=:client_id AND disabled_at IS NULL
    """), {"client_id": client_id})).mappings().first()


async def begin_authorization(
    db,
    *,
    user_id: int,
    client_id: str,
    redirect_uri: str,
    response_type: str,
    scope: str | None,
    state: str | None,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
) -> dict[str, Any]:
    client = await _load_client(db, client_id)
    if client is None:
        raise OAuthProtocolError("unauthorized_client", "Unknown OAuth client.")
    if redirect_uri not in tuple(client["redirect_uris"] or ()):
        raise OAuthProtocolError("invalid_request", "redirect_uri is not registered.")
    if response_type != "code":
        raise OAuthProtocolError(
            "unsupported_response_type", "Only response_type=code is supported."
        )
    if resource != mcp_resource_url():
        raise OAuthProtocolError("invalid_target", "resource does not identify this MCP server.")
    if code_challenge_method != "S256" or not PKCE_CHALLENGE_RE.fullmatch(code_challenge):
        raise OAuthProtocolError(
            "invalid_request", "PKCE S256 code_challenge is required."
        )
    scopes = _scope_tuple(scope, default_read=True)
    request_id = _plain("hgo_req_", 32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=AUTH_REQUEST_SECONDS)
    await db.execute(text("""
        INSERT INTO community.oauth_authorization_requests(
            request_hash,user_id,client_id,redirect_uri,scopes,state,resource,
            code_challenge,expires_at
        ) VALUES (
            :request_hash,:user_id,:client_id,:redirect_uri,:scopes,:state,
            :resource,:code_challenge,:expires_at
        )
    """), {
        "request_hash": _digest(request_id),
        "user_id": user_id,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scopes": list(scopes),
        "state": state,
        "resource": resource,
        "code_challenge": code_challenge,
        "expires_at": expires,
    })
    await db.commit()
    return {
        "request_id": request_id,
        "client_name": client["client_name"] or "MCP client",
        "scopes": list(scopes),
    }


async def complete_authorization(
    db, *, user_id: int, request_id: str, approve: bool
) -> str:
    row = (await db.execute(text("""
        SELECT id,client_id,redirect_uri,scopes,state,resource,code_challenge
        FROM community.oauth_authorization_requests
        WHERE request_hash=:digest AND user_id=:user_id AND expires_at>now()
        FOR UPDATE
    """), {"digest": _digest(request_id), "user_id": user_id})).mappings().first()
    if row is None:
        raise OAuthProtocolError(
            "invalid_request", "Authorization request expired or is no longer valid."
        )
    await db.execute(text("""
        DELETE FROM community.oauth_authorization_requests WHERE id=:id
    """), {"id": row["id"]})
    if not approve:
        await db.commit()
        return _redirect_with(
            row["redirect_uri"], error="access_denied", state=row["state"]
        )

    code = _plain("hgo_ac_", 32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=AUTH_CODE_SECONDS)
    await db.execute(text("""
        INSERT INTO community.oauth_authorization_codes(
            code_hash,user_id,client_id,redirect_uri,scopes,resource,
            code_challenge,expires_at
        ) VALUES (
            :code_hash,:user_id,:client_id,:redirect_uri,:scopes,:resource,
            :code_challenge,:expires_at
        )
    """), {
        "code_hash": _digest(code),
        "user_id": user_id,
        "client_id": row["client_id"],
        "redirect_uri": row["redirect_uri"],
        "scopes": row["scopes"],
        "resource": row["resource"],
        "code_challenge": row["code_challenge"],
        "expires_at": expires,
    })
    await db.commit()
    return _redirect_with(row["redirect_uri"], code=code, state=row["state"])


async def _issue_token_pair(
    db, *, user_id: int, client_id: str, scopes: tuple[str, ...], resource: str
) -> dict[str, Any]:
    access = _plain("hgo_at_", 32)
    refresh = _plain("hgo_rt_", 40)
    access_expiry = datetime.now(timezone.utc) + timedelta(seconds=ACCESS_TOKEN_SECONDS)
    refresh_expiry = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS)
    await db.execute(text("""
        INSERT INTO community.oauth_access_tokens(
            token_hash,user_id,client_id,scopes,resource,expires_at
        ) VALUES (:token_hash,:user_id,:client_id,:scopes,:resource,:expires_at)
    """), {
        "token_hash": _digest(access),
        "user_id": user_id,
        "client_id": client_id,
        "scopes": list(scopes),
        "resource": resource,
        "expires_at": access_expiry,
    })
    await db.execute(text("""
        INSERT INTO community.oauth_refresh_tokens(
            token_hash,user_id,client_id,scopes,resource,expires_at
        ) VALUES (:token_hash,:user_id,:client_id,:scopes,:resource,:expires_at)
    """), {
        "token_hash": _digest(refresh),
        "user_id": user_id,
        "client_id": client_id,
        "scopes": list(scopes),
        "resource": resource,
        "expires_at": refresh_expiry,
    })
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": ACCESS_TOKEN_SECONDS,
        "refresh_token": refresh,
        "scope": " ".join(scopes),
    }


async def exchange_authorization_code(
    db,
    *,
    client_id: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
    resource: str,
) -> dict[str, Any]:
    if resource != mcp_resource_url():
        raise OAuthProtocolError("invalid_target", "resource does not identify this MCP server.")
    if await _load_client(db, client_id) is None:
        raise OAuthProtocolError("invalid_client", "Unknown OAuth client.", status_code=401)
    row = (await db.execute(text("""
        SELECT id,user_id,client_id,redirect_uri,scopes,resource,code_challenge
        FROM community.oauth_authorization_codes
        WHERE code_hash=:digest AND expires_at>now() AND used_at IS NULL
        FOR UPDATE
    """), {"digest": _digest(code)})).mappings().first()
    if row is None:
        raise OAuthProtocolError("invalid_grant", "Authorization code is invalid or expired.")
    if (
        row["client_id"] != client_id
        or row["redirect_uri"] != redirect_uri
        or row["resource"] != resource
    ):
        raise OAuthProtocolError("invalid_grant", "Authorization code binding does not match.")
    if not _verify_pkce(code_verifier, row["code_challenge"]):
        raise OAuthProtocolError("invalid_grant", "PKCE verification failed.")

    await db.execute(text("""
        UPDATE community.oauth_authorization_codes SET used_at=now() WHERE id=:id
    """), {"id": row["id"]})
    result = await _issue_token_pair(
        db,
        user_id=int(row["user_id"]),
        client_id=client_id,
        scopes=tuple(row["scopes"] or ()),
        resource=resource,
    )
    await db.commit()
    return result


async def refresh_access_token(
    db,
    *,
    client_id: str,
    refresh_token: str,
    scope: str | None,
    resource: str,
) -> dict[str, Any]:
    if resource != mcp_resource_url():
        raise OAuthProtocolError("invalid_target", "resource does not identify this MCP server.")
    if await _load_client(db, client_id) is None:
        raise OAuthProtocolError("invalid_client", "Unknown OAuth client.", status_code=401)
    row = (await db.execute(text("""
        SELECT id,user_id,client_id,scopes,resource
        FROM community.oauth_refresh_tokens
        WHERE token_hash=:digest AND expires_at>now() AND revoked_at IS NULL
        FOR UPDATE
    """), {"digest": _digest(refresh_token)})).mappings().first()
    if row is None or row["client_id"] != client_id or row["resource"] != resource:
        raise OAuthProtocolError("invalid_grant", "Refresh token is invalid or expired.")
    granted = tuple(row["scopes"] or ())
    requested = _scope_tuple(scope) if scope else granted
    if not set(requested).issubset(granted):
        raise OAuthProtocolError("invalid_scope", "Requested scope exceeds the original grant.")

    await db.execute(text("""
        UPDATE community.oauth_refresh_tokens SET revoked_at=now() WHERE id=:id
    """), {"id": row["id"]})
    result = await _issue_token_pair(
        db,
        user_id=int(row["user_id"]),
        client_id=client_id,
        scopes=requested,
        resource=resource,
    )
    await db.commit()
    return result


async def resolve_access_token(
    db, token: str, *, expected_resource: str
) -> dict[str, Any] | None:
    if not token.startswith("hgo_at_"):
        return None
    row = (await db.execute(text("""
        SELECT t.id,t.user_id,t.client_id,t.scopes,t.resource,
               u.username,u.display_name,u.email,u.role,u.avatar_path
        FROM community.oauth_access_tokens t
        JOIN community.oauth_clients c
          ON c.client_id=t.client_id AND c.disabled_at IS NULL
        JOIN community.users u
          ON u.id=t.user_id AND u.status='active'
        WHERE t.token_hash=:digest
          AND t.revoked_at IS NULL
          AND t.expires_at>now()
          AND t.resource=:resource
    """), {
        "digest": _digest(token),
        "resource": expected_resource,
    })).mappings().first()
    if row is None:
        return None
    await db.execute(text("""
        UPDATE community.oauth_access_tokens
        SET last_used_at=now()
        WHERE id=:id AND (last_used_at IS NULL OR last_used_at<now()-interval '5 minutes')
    """), {"id": row["id"]})
    await db.commit()
    return dict(row)
