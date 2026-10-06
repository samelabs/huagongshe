"""OAuth 2.1 HTTP adapter for the HGS MCP authorization flow."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import (
    APIRouter, Depends, Form, HTTPException, Query, Request
)
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .core.database import get_db
from .core.security import Actor, current_session
from .rate_limit_http import enforce_http
from .services import oauth as svc
from .services.oauth import OAuthError

router = APIRouter(tags=["oauth"])


class RegistrationBody(BaseModel):
    redirect_uris: list[str] = Field(min_length=1, max_length=20)
    client_name: str | None = Field(default=None, max_length=120)
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = Field(
        default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])
    scope: str | None = Field(default=None, max_length=200)
    application_type: str = Field(default="web", max_length=20)


def _oauth_error(exc: OAuthError, *, status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"error": exc.error, "error_description": exc.description},
        status_code=status,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _redirect_params(uri: str, values: dict[str, str | None]) -> str:
    parsed = urlsplit(uri)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((key, value) for key, value in values.items() if value is not None)
    return urlunsplit((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        urlencode(query),
        parsed.fragment,
    ))


def _check_same_origin_post(request: Request) -> None:
    base = svc.issuer_url()
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if origin:
        if origin.rstrip("/") != base:
            raise HTTPException(403, "OAuth consent origin is invalid.")
        return
    if not referer or not referer.startswith(f"{base}/oauth/authorize"):
        raise HTTPException(403, "OAuth consent origin is missing.")


@router.get("/oauth/resource-metadata")
async def resource_metadata():
    return svc.protected_resource_metadata()


@router.get("/oauth/authorization-server-metadata")
async def authorization_server_metadata():
    return svc.authorization_server_metadata()


@router.post("/oauth/register", status_code=201)
async def register_client(body: RegistrationBody, db=Depends(get_db)):
    await enforce_http("oauth-register", "global", 120, 3600)
    try:
        return await svc.register_client(
            db,
            redirect_uris=body.redirect_uris,
            client_name=body.client_name,
            token_endpoint_auth_method=body.token_endpoint_auth_method,
            grant_types=body.grant_types,
            response_types=body.response_types,
            scope=body.scope,
            application_type=body.application_type,
        )
    except OAuthError as exc:
        return _oauth_error(exc)


@router.get("/oauth/authorize/inspect")
async def inspect_authorization(
    response_type: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    resource: str,
    scope: str | None = None,
    state: str | None = None,
    actor: Actor = Depends(current_session),
    db=Depends(get_db),
):
    del state
    try:
        data = await svc.validate_authorization_request(
            db,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    except OAuthError as exc:
        return _oauth_error(exc)
    return {
        "client_id": data["client_id"],
        "client_name": data["client_name"],
        "redirect_uri": data["redirect_uri"],
        "scopes": list(data["scopes"]),
        "user": {
            "id": actor.id,
            "username": actor.username,
            "display_name": actor.display_name,
        },
    }


@router.post("/oauth/authorize")
async def authorize(
    request: Request,
    response_type: str = Form(...),
    client_id: str = Form(...),
    redirect_uri: str = Form(...),
    code_challenge: str = Form(...),
    code_challenge_method: str = Form(...),
    resource: str = Form(...),
    scope: str | None = Form(default=None),
    state: str | None = Form(default=None),
    decision: str = Form(...),
    actor: Actor = Depends(current_session),
    db=Depends(get_db),
):
    _check_same_origin_post(request)
    await enforce_http("oauth-authorize", str(actor.id), 60, 300)
    try:
        data = await svc.validate_authorization_request(
            db,
            response_type=response_type,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scope=scope,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            resource=resource,
        )
    except OAuthError as exc:
        return _oauth_error(exc)

    if decision == "deny":
        return RedirectResponse(
            _redirect_params(
                redirect_uri,
                {"error": "access_denied", "state": state},
            ),
            status_code=303,
        )
    if decision != "allow":
        return _oauth_error(OAuthError("invalid_request", "Unknown consent decision."))

    code = await svc.create_authorization_code(
        db,
        user_id=actor.id,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=tuple(data["scopes"]),
        code_challenge=code_challenge,
        resource=resource,
    )
    return RedirectResponse(
        _redirect_params(redirect_uri, {"code": code, "state": state}),
        status_code=303,
    )


@router.post("/oauth/token")
async def token(
    grant_type: str = Form(..., min_length=1, max_length=40),
    client_id: str = Form(..., min_length=1, max_length=300),
    resource: str = Form(..., min_length=1, max_length=2000),
    code: str | None = Form(default=None, max_length=240),
    redirect_uri: str | None = Form(default=None, max_length=2000),
    code_verifier: str | None = Form(default=None, max_length=200),
    refresh_token: str | None = Form(default=None, max_length=300),
    scope: str | None = Form(default=None, max_length=300),
    db=Depends(get_db),
):
    await enforce_http("oauth-token", client_id[:80], 180, 60)
    try:
        if grant_type == "authorization_code":
            if not code or not redirect_uri or not code_verifier:
                raise OAuthError(
                    "invalid_request",
                    "code, redirect_uri, and code_verifier are required.",
                )
            result = await svc.exchange_authorization_code(
                db,
                code=code,
                client_id=client_id,
                redirect_uri=redirect_uri,
                code_verifier=code_verifier,
                resource=resource,
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise OAuthError("invalid_request", "refresh_token is required.")
            result = await svc.exchange_refresh_token(
                db,
                refresh_token=refresh_token,
                client_id=client_id,
                resource=resource,
                scope=scope,
            )
        else:
            raise OAuthError("unsupported_grant_type", "Unsupported grant_type.")
    except OAuthError as exc:
        return _oauth_error(exc)
    return JSONResponse(
        result,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )
