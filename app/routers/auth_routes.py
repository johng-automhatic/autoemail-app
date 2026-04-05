"""Authentication routes: login, callback, logout."""

import json
import hashlib
import logging
import os
import tempfile
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from app.auth import get_login_url, acquire_token_by_code
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

# Directory to store auth flows — use /home which persists on Azure App Service
FLOW_DIR = os.path.join("/home", "auth_flows") if os.path.isdir("/home/site") else os.path.join(tempfile.gettempdir(), "auth_flows")
os.makedirs(FLOW_DIR, exist_ok=True)


def _flow_path(state: str) -> str:
    """Get file path for a given auth flow state."""
    safe = hashlib.sha256(state.encode()).hexdigest()[:16]
    return os.path.join(FLOW_DIR, f"flow_{safe}.json")


@router.get("/login")
async def login(request: Request):
    """Redirect user to Microsoft Entra ID login page."""
    settings = get_settings()
    flow = get_login_url(settings)

    # Store the auth flow on disk keyed by state parameter
    state = flow.get("state", "")
    flow_file = _flow_path(state)
    with open(flow_file, "w") as f:
        json.dump(flow, f)

    # Store just the state in the session cookie (small enough to fit)
    request.session["auth_state"] = state
    return RedirectResponse(url=flow["auth_uri"])


@router.get("/callback")
async def auth_callback(request: Request):
    """Handle the Entra ID callback after user authenticates."""
    settings = get_settings()

    # Recover the auth flow from disk using the state
    state = request.query_params.get("state", "") or request.session.get("auth_state", "")
    if not state:
        raise HTTPException(status_code=400, detail="No auth state found")

    flow_file = _flow_path(state)
    if not os.path.exists(flow_file):
        raise HTTPException(status_code=400, detail="Auth flow expired. Please try logging in again.")

    with open(flow_file, "r") as f:
        auth_flow = json.load(f)

    # Clean up the flow file
    try:
        os.remove(flow_file)
    except OSError:
        pass

    try:
        result = await acquire_token_by_code(
            settings,
            auth_flow,
            dict(request.query_params),
        )
    except Exception as e:
        logger.error("Token exchange failed: %s", str(e))
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(f"Token exchange error: {str(e)}", status_code=401)

    # Store tokens in session
    request.session["id_token"] = result.get("id_token")
    request.session["access_token"] = result.get("access_token")

    # Extract user info from id_token claims
    id_claims = result.get("id_token_claims", {})
    request.session["user_name"] = id_claims.get("name", "")
    request.session["user_email"] = id_claims.get("preferred_username", "")
    request.session["user_roles"] = id_claims.get("roles", [])

    # Clean up
    request.session.pop("auth_state", None)

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
