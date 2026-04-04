"""Authentication routes: login, callback, logout."""

import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from app.auth import get_login_url, acquire_token_by_code
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/login")
async def login(request: Request):
    """Redirect user to Microsoft Entra ID login page."""
    settings = get_settings()
    flow = get_login_url(settings)
    # Store the auth flow in session for callback validation
    request.session["auth_flow"] = flow
    return RedirectResponse(url=flow["auth_uri"])


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle the Entra ID callback after user authenticates."""
    settings = get_settings()
    auth_flow = request.session.get("auth_flow")
    if not auth_flow:
        raise HTTPException(status_code=400, detail="No auth flow in session")

    result = await acquire_token_by_code(
        settings,
        auth_flow,
        dict(request.query_params),
    )

    # Store tokens in session
    request.session["id_token"] = result.get("id_token")
    request.session["access_token"] = result.get("access_token")

    # Extract user info from id_token claims
    id_claims = result.get("id_token_claims", {})
    request.session["user_name"] = id_claims.get("name", "")
    request.session["user_email"] = id_claims.get("preferred_username", "")
    request.session["user_roles"] = id_claims.get("roles", [])

    # Clean up auth flow from session
    request.session.pop("auth_flow", None)

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
