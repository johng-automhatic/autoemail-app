"""Microsoft Entra ID (Azure AD) authentication for FastAPI.

Handles:
- MSAL-based login redirect and token acquisition
- JWT validation against Entra ID discovery keys
- Role-based access control (Admin, Operator, Viewer)
- Session management via secure cookies
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import msal
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

# ── JWKS key cache ─────────────────────────────────────────────────────────────

_jwks_cache: dict = {"keys": [], "expires_at": datetime.min.replace(tzinfo=timezone.utc)}


async def _get_signing_keys(settings: Settings) -> list[dict]:
    """Fetch and cache Entra ID JWKS signing keys."""
    global _jwks_cache
    now = datetime.now(timezone.utc)
    if now < _jwks_cache["expires_at"]:
        return _jwks_cache["keys"]

    openid_config_url = f"{settings.authority}/v2.0/.well-known/openid-configuration"
    async with httpx.AsyncClient() as client:
        resp = await client.get(openid_config_url)
        jwks_uri = resp.json()["jwks_uri"]
        resp = await client.get(jwks_uri)
        keys = resp.json()["keys"]

    _jwks_cache = {"keys": keys, "expires_at": now + timedelta(hours=12)}
    return keys


# ── MSAL Confidential Client ──────────────────────────────────────────────────

def _get_msal_app(settings: Settings) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=settings.azure_client_id,
        client_credential=settings.azure_client_secret,
        authority=settings.authority,
    )


def get_login_url(settings: Settings, state: str = "") -> str:
    """Generate Entra ID authorization URL."""
    app = _get_msal_app(settings)
    flow = app.initiate_auth_code_flow(
        scopes=["openid", "profile", "email"],
        redirect_uri=settings.app_redirect_uri,
        state=state,
    )
    return flow


async def acquire_token_by_code(settings: Settings, auth_code_flow: dict, auth_response: dict) -> dict:
    """Exchange authorization code for tokens."""
    app = _get_msal_app(settings)
    result = app.acquire_token_by_auth_code_flow(auth_code_flow, auth_response)
    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Auth failed: {result.get('error_description', result['error'])}",
        )
    return result


# ── JWT Validation ─────────────────────────────────────────────────────────────

async def validate_token(token: str, settings: Settings) -> dict:
    """Validate an Entra ID JWT and return decoded claims."""
    keys = await _get_signing_keys(settings)

    # Try each signing key
    for key in keys:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=settings.azure_client_id,
                issuer=f"https://login.microsoftonline.com/{settings.azure_tenant_id}/v2.0",
                options={"verify_at_hash": False},
            )
            return claims
        except JWTError:
            continue

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
    )


# ── User model from claims ─────────────────────────────────────────────────────

class CurrentUser:
    """Parsed user info from Entra ID token claims."""

    def __init__(self, claims: dict):
        self.oid: str = claims.get("oid", "")
        self.email: str = claims.get("preferred_username", claims.get("email", ""))
        self.name: str = claims.get("name", self.email)
        self.roles: list[str] = claims.get("roles", [])

    @property
    def is_admin(self) -> bool:
        return "EmailFlow.Admin" in self.roles

    @property
    def is_operator(self) -> bool:
        return "EmailFlow.Operator" in self.roles or self.is_admin

    @property
    def is_viewer(self) -> bool:
        return any(r in self.roles for r in ["EmailFlow.Admin", "EmailFlow.Operator", "EmailFlow.Viewer"])


# ── FastAPI dependencies ───────────────────────────────────────────────────────

async def get_current_user(request: Request) -> CurrentUser:
    """Extract and validate the current user from the session cookie.

    In production, the session stores the id_token after Entra ID login.
    For development/testing, you can set DEV_BYPASS_AUTH=1 in .env.
    """
    settings = get_settings()

    token = request.session.get("id_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please sign in.",
            headers={"Location": "/auth/login"},
        )

    claims = await validate_token(token, settings)
    return CurrentUser(claims)


async def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Require EmailFlow.Admin role."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return user


async def require_operator(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Require EmailFlow.Operator or Admin role."""
    if not user.is_operator:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Operator role required")
    return user


async def require_viewer(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Require any EmailFlow role."""
    if not user.is_viewer:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return user
