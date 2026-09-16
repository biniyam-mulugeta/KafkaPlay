"""OIDC login.

Authorization-code flow with PKCE against any compliant provider: Keycloak,
Google, GitHub (via its OIDC-ish endpoints), Microsoft Entra.

Role mapping is explicit. A claim is read from the ID token and matched
against operator-configured values; anything unmatched falls back to the
configured default, which is `viewer`. Nobody becomes an admin by accident.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import Settings
from app.logging import get_logger
from app.store.models import Role

log = get_logger(__name__)


class OidcError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OidcEndpoints:
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None = None
    issuer: str | None = None


@dataclass(frozen=True, slots=True)
class PkcePair:
    verifier: str
    challenge: str

    @classmethod
    def generate(cls) -> PkcePair:
        verifier = secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return cls(verifier=verifier, challenge=challenge)


@dataclass(frozen=True, slots=True)
class OidcProfile:
    subject: str
    username: str
    email: str | None
    display_name: str | None
    claims: dict[str, Any]


async def discover(issuer_url: str, *, timeout: float = 10.0) -> OidcEndpoints:
    """Fetch the provider's well-known configuration."""
    url = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise OidcError(f"cannot reach the OIDC provider at {url}: {exc}") from exc

    required = ("authorization_endpoint", "token_endpoint", "jwks_uri")
    missing = [name for name in required if name not in payload]
    if missing:
        raise OidcError(f"OIDC discovery document is missing: {', '.join(missing)}")

    return OidcEndpoints(
        authorization_endpoint=payload["authorization_endpoint"],
        token_endpoint=payload["token_endpoint"],
        jwks_uri=payload["jwks_uri"],
        userinfo_endpoint=payload.get("userinfo_endpoint"),
        issuer=payload.get("issuer"),
    )


def authorization_url(
    endpoints: OidcEndpoints,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    nonce: str,
    pkce: PkcePair,
    scopes: str = "openid profile email",
) -> str:
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": pkce.challenge,
        "code_challenge_method": "S256",
    }
    return f"{endpoints.authorization_endpoint}?{urlencode(params)}"


async def exchange_code(
    endpoints: OidcEndpoints,
    *,
    code: str,
    client_id: str,
    client_secret: str | None,
    redirect_uri: str,
    pkce: PkcePair,
    timeout: float = 10.0,
) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": pkce.verifier,
    }
    if client_secret:
        data["client_secret"] = client_secret

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoints.token_endpoint, data=data)
    except httpx.HTTPError as exc:
        raise OidcError(f"token exchange failed: {exc}") from exc

    if response.status_code >= 400:
        raise OidcError(f"token exchange returned HTTP {response.status_code}")

    payload: dict[str, Any] = response.json()
    if "id_token" not in payload:
        raise OidcError("the provider did not return an id_token")
    return payload


def decode_id_token_unverified(id_token: str) -> dict[str, Any]:
    """Decode an ID token WITHOUT verifying its signature.

    For tests and for inspecting a token during setup. Never call this on a
    request path -- an unverified token is attacker-controlled data. The
    request path uses verify_id_token().
    """
    import jwt

    return dict(jwt.decode(id_token, options={"verify_signature": False}))


async def verify_id_token(
    id_token: str,
    *,
    endpoints: OidcEndpoints,
    audience: str,
    nonce: str | None = None,
) -> dict[str, Any]:
    import jwt
    from jwt import PyJWKClient

    try:
        jwks = PyJWKClient(endpoints.jwks_uri)
        signing_key = jwks.get_signing_key_from_jwt(id_token)
        claims: dict[str, Any] = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384"],
            audience=audience,
            issuer=endpoints.issuer,
            options={"require": ["exp", "iat"]},
        )
    except Exception as exc:
        raise OidcError(f"the ID token could not be verified: {exc}") from exc

    # A replayed authorization response would otherwise be accepted.
    if nonce is not None and claims.get("nonce") != nonce:
        raise OidcError("the ID token nonce does not match this login attempt")

    return claims


def map_role(claims: dict[str, Any], settings: Settings) -> Role:
    """Map provider claims onto a console role.

    Explicit and least-privilege: an unrecognised group gets `viewer`, never
    something higher.
    """
    claim_name = settings.oidc_role_claim
    raw = claims.get(claim_name)

    values: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    elif isinstance(raw, dict):
        # Keycloak nests roles under realm_access.roles and similar.
        nested = raw.get("roles")
        if isinstance(nested, list):
            values = [str(item) for item in nested]

    lowered = {value.strip().lower() for value in values}

    if settings.oidc_admin_value and settings.oidc_admin_value.lower() in lowered:
        return Role.ADMIN
    if settings.oidc_operator_value and settings.oidc_operator_value.lower() in lowered:
        return Role.OPERATOR
    return Role.VIEWER


def profile_from_claims(claims: dict[str, Any], settings: Settings) -> OidcProfile:
    username = (
        claims.get(settings.oidc_username_claim)
        or claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
    )
    if not username:
        raise OidcError("the ID token contains no usable username claim")

    return OidcProfile(
        subject=str(claims.get("sub", username)),
        username=str(username),
        email=claims.get("email"),
        display_name=claims.get("name") or claims.get("given_name"),
        claims=claims,
    )
