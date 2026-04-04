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
    start_scheduler()
    yield
    logger.info("Shutting down Email Flow Manager")
    stop_scheduler()


# ── App ────────────────────────────────────────────────────────────────────────

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
)

# Session middleware for auth (cookie-based sessions)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="efm_session",
    max_age=3600 * 8,  # 8-hour session
)

# Static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(auth_routes.router)
app.include_router(dashboard.router)
app.include_router(flows.router)
app.include_router(email_log.router)


# ── Exception handler for unauthenticated users ───────────────────────────────

@app.exception_handler(401)
async def unauthorized_redirect(request: Request, exc):
    """Redirect unauthenticated users to login."""
    return RedirectResponse(url="/auth/login")
