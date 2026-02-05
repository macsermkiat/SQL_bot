"""
FastAPI application with authentication, rate limiting, and security headers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import (
    create_session_token,
    get_current_user_from_cookie,
    get_user_store,
    require_auth,
)
from app.chat import get_orchestrator
from app.config import get_settings
from app.db import get_db
from app.models import ChatRequest, ChatResponse, UserInfo
from app.rate_limit import get_login_limiter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------- Security headers middleware ----------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


# ---------- App setup ----------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Starting KCMH SQL Bot...")
    settings = get_settings()
    logger.info("Using model: %s", settings.claude_model)

    # Pre-load user store
    store = get_user_store()
    logger.info("User store loaded: %d users", store.user_count)

    # Test database connection
    db = get_db()
    if db.test_connection():
        logger.info("Database connection successful")
    else:
        logger.warning("Database connection failed - queries will not work")

    yield

    # Cleanup
    db.close()
    logger.info("KCMH SQL Bot stopped")


app = FastAPI(
    title="KCMH SQL Bot",
    description="Read-only analytics chatbot for KCMH Hospital Information System",
    version="0.3.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

app.add_middleware(SecurityHeadersMiddleware)

settings = get_settings()

app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

templates = Jinja2Templates(directory=str(settings.templates_dir))


def _is_api_request(request: Request) -> bool:
    """Check if request expects JSON (API) or HTML (browser)."""
    accept = request.headers.get("accept", "")
    return "application/json" in accept or request.url.path.startswith("/api/")


def _get_client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For if behind proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---------- Auth routes ----------


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve login page. Redirect to chat if already authenticated."""
    user = get_current_user_from_cookie(request)
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    """Authenticate user and set session cookie."""
    client_ip = _get_client_ip(request)
    limiter = get_login_limiter()

    # Check rate limit
    if limiter.is_blocked(client_ip):
        remaining = limiter.remaining_seconds(client_ip)
        logger.warning("Rate limited login attempt from %s", client_ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": f"Too many failed attempts. Please try again in {remaining} seconds."},
            status_code=429,
        )

    store = get_user_store()
    user = store.verify(email, password)

    if user is None:
        limiter.record_failure(client_ip)
        logger.info("Failed login attempt for: %s from %s", email, client_ip)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password"},
            status_code=401,
        )

    limiter.record_success(client_ip)
    logger.info("Successful login: %s (role=%s)", user.email, user.role)
    token = create_session_token(user)

    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/logout")
async def logout():
    """Clear session cookie and redirect to login."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(key=settings.session_cookie_name)
    return response


# ---------- Main routes ----------


@app.get("/", response_class=HTMLResponse)
async def get_ui(request: Request, user: UserInfo = Depends(require_auth)):
    """Serve the chat UI for authenticated users."""
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"user": user},
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: UserInfo = Depends(require_auth)):
    """Handle chat message and return response."""
    try:
        orchestrator = get_orchestrator()
        response = await orchestrator.handle_message(request)

        # Strip sensitive fields for standard users
        if user.role != "super_user":
            response.sql = None
            response.query_result = None
            response.sanity_checks = []

        return response
    except Exception as e:
        logger.exception("Chat error for user %s", user.email)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
async def health():
    """Health check endpoint (no auth required)."""
    db = get_db()
    db_ok = db.test_connection()
    return {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "disconnected",
    }


# ---------- Exception handlers ----------


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with appropriate response format."""
    if exc.status_code == 401:
        if _is_api_request(request):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )
        return RedirectResponse(url="/login", status_code=302)

    if exc.status_code == 403:
        if _is_api_request(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Forbidden"},
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": 403,
                "message": "You do not have permission to access this resource.",
                "redirect_url": "/",
                "button_text": "Back to Chat",
            },
            status_code=403,
        )

    if exc.status_code >= 500:
        if _is_api_request(request):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": "Internal server error"},
            )
        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": exc.status_code,
                "message": "Something went wrong. Please try again.",
                "redirect_url": "/",
                "button_text": "Back to Chat",
            },
            status_code=exc.status_code,
        )

    # Default: return JSON for any other HTTP exception
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
