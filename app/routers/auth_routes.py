"""Authentication routes: login, callback, logout.

Uses MSAL PublicClientApplication with PKCE (no client secret needed for
the auth code exchange, avoiding server-side flow storage issues).
Falls back to a simple approach: build the auth URL manually and exchange
the code with ConfidentialClientApplication.acquire_token_by_authorization_code().
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse

import msal
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _get_msal_app(settings):
    return msal.ConfidentialClientApplication(
        client_id=settings.azure_client_id,
        client_credential=settings.azure_client_secret,
        authority=settings.authority,
    )


@router.get("/login")
async def login(request: Request):
    """Redirect user to Microsoft Entra ID login page."""
    settings = get_settings()

    # Build auth URL manually — avoids needing to store the flow object
    params = {
        "client_id": settings.azure_client_id,
        "response_type": "code",
        "redirect_uri": settings.app_redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email User.Read",
        "state": "login",
    }
    auth_url = f"{settings.authority}/oauth2/v2.0/authorize?{urlencode(params)}"
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle the Entra ID callback after user authenticates."""
    settings = get_settings()

    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        error_desc = request.query_params.get("error_description", error)
        return PlainTextResponse(f"Login error: {error_desc}", status_code=401)

    if not code:
        return PlainTextResponse("No authorization code received.", status_code=400)

    # Exchange the code for tokens using MSAL
    app = _get_msal_app(settings)
    try:
        result = app.acquire_token_by_authorization_code(
            code=code,
            scopes=["User.Read"],
            redirect_uri=settings.app_redirect_uri,
        )
    except Exception as e:
        logger.error("Token exchange failed: %s", str(e))
        return PlainTextResponse(f"Token exchange error: {str(e)}", status_code=401)

    if "error" in result:
        error_desc = result.get("error_description", result["error"])
        logger.error("Auth failed: %s", error_desc)
        return PlainTextResponse(f"Auth failed: {error_desc}", status_code=401)

    # Store tokens in session
    request.session["id_token"] = result.get("id_token")
    request.session["access_token"] = result.get("access_token")

    # Extract user info from id_token claims
    id_claims = result.get("id_token_claims", {})
    request.session["user_name"] = id_claims.get("name", "")
    request.session["user_email"] = id_claims.get("preferred_username", "")
    request.session["user_roles"] = id_claims.get("roles", [])

    logger.info("User logged in: %s", request.session.get("user_email"))
    return RedirectResponse(url="/")


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to Entra ID logout."""
    settings = get_settings()
    request.session.clear()
    logout_url = (
        f"{settings.authority}/oauth2/v2.0/logout"
        f"?post_logout_redirect_uri={settings.app_redirect_uri.rsplit('/auth/', 1)[0]}"
    )
    return RedirectResponse(url=logout_url)
