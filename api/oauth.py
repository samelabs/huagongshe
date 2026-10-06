"""OAuth 2.1 HTTP adapter for MCP account linking."""
from __future__ import annotations

import html
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .core.database import get_db
from .core.security import Actor, current_session, optional_actor
from .rate_limit_http import enforce_http
from .services import oauth as svc

router = APIRouter(prefix="/oauth", tags=["oauth"])


def _oauth_error(exc: svc.OAuthProtocolError) -> JSONResponse:
    response = JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=exc.status_code,
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/protected-resource-metadata")
async def protected_resource_metadata():
    return svc.protected_resource_metadata()


@router.get("/authorization-server-metadata")
async def authorization_server_metadata():
    return svc.authorization_server_metadata()


@router.post("/register")
async def register(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    await enforce_http("oauth-register", "global", 120, 3600)
    try:
        return await svc.register_client(
            db,
            redirect_uris=list(body.get("redirect_uris") or []),
            client_name=body.get("client_name"),
            token_endpoint_auth_method=body.get("token_endpoint_auth_method"),
            grant_types=body.get("grant_types"),
            response_types=body.get("response_types"),
            application_type=body.get("application_type"),
        )
    except svc.OAuthProtocolError as exc:
        return _oauth_error(exc)


@router.get("/authorize")
async def authorize(
    request: Request,
    client_id: str = Query(..., min_length=1, max_length=300),
    redirect_uri: str = Query(..., min_length=1, max_length=2000),
    response_type: str = Query(..., min_length=1, max_length=30),
    scope: str = Query(default="", max_length=300),
    state: str | None = Query(default=None, max_length=1000),
    code_challenge: str = Query(..., min_length=1, max_length=200),
    code_challenge_method: str = Query(..., min_length=1, max_length=20),
    resource: str = Query(..., min_length=1, max_length=2000),
    actor: Actor | None = Depends(optional_actor),
    db: AsyncSession = Depends(get_db),
):
    if actor is None or actor.auth_kind != "session":
        next_path = "/oauth/authorize"
        if request.url.query:
            next_path += "?" + request.url.query
        return RedirectResponse(
            url=f"/login?next={quote(next_path, safe='')}",
            status_code=302,
        )
    await enforce_http("oauth-authorize", str(actor.id), 60, 300)
    try:
        pending = await svc.begin_authorization(
            db,
            user_id=actor.id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            response_type=response_type,
            scope=scope,
            state=state,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    except svc.OAuthProtocolError as exc:
        return _oauth_error(exc)

    scopes = "".join(
        f"<li><code>{html.escape(value)}</code></li>" for value in pending["scopes"]
    )
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect HGS</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;background:#f6f7f8;color:#15171a;margin:0}}
main{{max-width:620px;margin:10vh auto;padding:32px;background:white;border:1px solid #e3e6e8;border-radius:16px}}
h1{{font-size:24px;margin:0 0 12px}} p{{line-height:1.6;color:#4b5563}}
code{{font-size:13px}} .actions{{display:flex;gap:12px;margin-top:28px}}
button{{border:1px solid #cfd4d9;border-radius:9px;padding:10px 18px;background:white;font:inherit;cursor:pointer}}
button.primary{{background:#111827;color:white;border-color:#111827}}
</style>
</head>
<body><main>
<p>HGS · 化工社</p>
<h1>Connect {html.escape(str(pending["client_name"]))}</h1>
<p>This connection will act as <strong>{html.escape(actor.display_name)}</strong>
for the permissions below.</p>
<ul>{scopes}</ul>
<form method="post" action="/oauth/authorize">
<input type="hidden" name="request_id" value="{html.escape(pending["request_id"])}">
<div class="actions">
<button type="submit" name="decision" value="deny">Cancel</button>
<button class="primary" type="submit" name="decision" value="approve">Allow</button>
</div>
</form>
</main></body></html>"""
    response = HTMLResponse(page)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@router.post("/authorize")
async def authorize_decision(
    request_id: str = Form(..., min_length=1, max_length=200),
    decision: str = Form(..., min_length=1, max_length=20),
    actor: Actor = Depends(current_session),
    db: AsyncSession = Depends(get_db),
):
    if decision not in ("approve", "deny"):
        return _oauth_error(
            svc.OAuthProtocolError("invalid_request", "decision must be approve or deny.")
        )
    try:
        redirect = await svc.complete_authorization(
            db,
            user_id=actor.id,
            request_id=request_id,
            approve=decision == "approve",
        )
    except svc.OAuthProtocolError as exc:
        return _oauth_error(exc)
    return RedirectResponse(redirect, status_code=303)


@router.post("/token")
async def token(
    grant_type: str = Form(..., min_length=1, max_length=40),
    client_id: str = Form(..., min_length=1, max_length=300),
    resource: str = Form(..., min_length=1, max_length=2000),
    code: str | None = Form(default=None, max_length=200),
    redirect_uri: str | None = Form(default=None, max_length=2000),
    code_verifier: str | None = Form(default=None, max_length=200),
    refresh_token: str | None = Form(default=None, max_length=300),
    scope: str | None = Form(default=None, max_length=300),
    db: AsyncSession = Depends(get_db),
):
    await enforce_http("oauth-token", client_id[:80], 180, 60)
    try:
        if grant_type == "authorization_code":
            if not code or not redirect_uri or not code_verifier:
                raise svc.OAuthProtocolError(
                    "invalid_request",
                    "code, redirect_uri, and code_verifier are required.",
                )
            result = await svc.exchange_authorization_code(
                db,
                client_id=client_id,
                code=code,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
                resource=resource,
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise svc.OAuthProtocolError(
                    "invalid_request", "refresh_token is required."
                )
            result = await svc.refresh_access_token(
                db,
                client_id=client_id,
                refresh_token=refresh_token,
                scope=scope,
                resource=resource,
            )
        else:
            raise svc.OAuthProtocolError(
                "unsupported_grant_type", "Unsupported OAuth grant_type."
            )
    except svc.OAuthProtocolError as exc:
        return _oauth_error(exc)

    response = JSONResponse(result)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response
