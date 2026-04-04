"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.routers import auth_routes, dashboard, flows, email_log
from app.services.scheduler import start_scheduler, stop_scheduler

# ── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Email Flow Manager")
    # Scheduler disabled until DB is connected and migrated
    # start_scheduler()
    yield
    logger.info("Shutting down Email Flow Manager")
    # stop_scheduler()


# ── App ────────────────────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# Session middleware for auth (cookie-based sessions)
# Note: https_only=False because App Service terminates SSL at the LB;
# the app sees HTTP internally even though the user is on HTTPS.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="efm_session",
    max_age=3600 * 8,  # 8-hour session
    same_site="lax",
    https_only=False,
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(auth_routes.router)
app.include_router(dashboard.router)
app.include_router(flows.router)
app.include_router(email_log.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Exception handler for unauthenticated users ───────────────────────────────

from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Redirect unauthenticated users to login, pass through other errors."""
    if exc.status_code == 401:
        # Don't redirect if already on an auth route to avoid loops
        if request.url.path.startswith("/auth/"):
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse("Authentication failed. Check Entra ID configuration.", status_code=401)
        return RedirectResponse(url="/auth/login")
    # Re-raise other HTTP exceptions
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
