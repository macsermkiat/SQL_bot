"""
FastAPI application with authentication, rate limiting, and security headers.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from contextlib import suppress

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import StreamingResponse

from app.auth import (
    create_session_token,
    get_current_user_from_cookie,
    get_user_store,
    require_auth,
)
from app.chat import get_orchestrator
from app.config import get_settings
from app.db import CancellableQuery, get_db
from app.models import ChatRequest, ChatResponse, UserInfo
from app.rate_limit import get_login_limiter
from app.session import SessionOwnershipError, get_session_manager

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


async def _periodic_login_limiter_cleanup(
    interval_seconds: float = 600,
) -> None:
    """Clean expired login-attempt records at a fixed interval."""
    while True:
        await asyncio.sleep(interval_seconds)
        get_login_limiter().cleanup()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info("Starting KCMH SQL Bot...")
    settings = get_settings()
    settings.validate_runtime_safety()
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

    limiter_cleanup_task = asyncio.create_task(
        _periodic_login_limiter_cleanup(),
        name="login-rate-limiter-cleanup",
    )
    try:
        yield
    finally:
        limiter_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await limiter_cleanup_task
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
async def login_page(request: Request, registered: str | None = None):
    """Serve login page. Redirect to chat if already authenticated."""
    user = get_current_user_from_cookie(request)
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return templates.TemplateResponse(
        request, "login.html", {"error": None, "registered": registered is not None},
    )


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
        secure=settings.secure_cookies or settings.app_env == "production",
    )
    return response


import re

ALLOWED_EMAIL_DOMAINS = {"chula.ac.th", "chulahospital.org"}
_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")


def _render_register(
    request: Request,
    *,
    error: str | None = None,
    success: str | None = None,
    form_data: dict | None = None,
    status_code: int = 200,
):
    """Render the registration template with consistent context."""
    return templates.TemplateResponse(
        request,
        "register.html",
        {"error": error, "success": success, "form_data": form_data or {}},
        status_code=status_code,
    )


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve registration page. Redirect to chat if already authenticated."""
    user = get_current_user_from_cookie(request)
    if user is not None:
        return RedirectResponse(url="/", status_code=302)
    return _render_register(request)


@app.post("/register")
async def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    department: str = Form(...),
    employee_id: str = Form(...),
):
    """Handle user registration. Employee ID is used as the login password."""
    # Strip all inputs once at the boundary
    name = name.strip()
    email = email.strip().lower()
    department = department.strip()
    employee_id = employee_id.strip()

    form_data = {
        "name": name,
        "email": email,
        "department": department,
        "employee_id": employee_id,
    }

    # Rate limit registration attempts
    client_ip = _get_client_ip(request)
    limiter = get_login_limiter()
    if limiter.is_blocked(client_ip):
        remaining = limiter.remaining_seconds(client_ip)
        return _render_register(
            request,
            error=f"Too many attempts. Please try again in {remaining} seconds.",
            form_data=form_data,
            status_code=429,
        )

    # Validate required fields
    if not all([name, email, department, employee_id]):
        return _render_register(
            request, error="All fields are required.", form_data=form_data, status_code=400,
        )

    # Validate email format
    if not _EMAIL_PATTERN.match(email):
        return _render_register(
            request, error="Please enter a valid email address.", form_data=form_data, status_code=400,
        )

    # Validate email domain
    domain = email.rsplit("@", 1)[-1]
    if domain not in ALLOWED_EMAIL_DOMAINS:
        return _render_register(
            request,
            error="Email must be @chula.ac.th or @chulahospital.org",
            form_data=form_data,
            status_code=400,
        )

    # Validate employee ID: must be exactly 7 digits
    if not re.fullmatch(r"\d{7}", employee_id):
        return _render_register(
            request,
            error="Hospital Code (ID) must be exactly 7 digits.",
            form_data=form_data,
            status_code=400,
        )

    # Register: employee_id stored in CSV ID column (used as login password)
    store = get_user_store()
    result = store.register(
        name=name,
        password=employee_id,
        department=department,
        email=email,
        csv_path=settings.users_csv_path,
    )

    if result is None:
        limiter.record_failure(client_ip)
        return _render_register(
            request, error="This email is already registered.", form_data=form_data, status_code=409,
        )

    limiter.record_success(client_ip)
    logger.info("New user registered: %s", email)
    return RedirectResponse(
        url="/login?registered=1",
        status_code=302,
    )


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
        response = await orchestrator.handle_message(
            request,
            user_email=user.email,
            user_role=user.role,
        )

        # Strip sensitive fields for standard users
        if user.role != "super_user":
            response.sql = None
            response.query_result = None
            response.sanity_checks = []

        return response
    except SessionOwnershipError:
        raise HTTPException(status_code=403, detail="Forbidden")
    except Exception as e:
        logger.exception("Chat error for user %s", user.email)
        detail = str(e) if user.role == "super_user" else "Internal server error"
        raise HTTPException(status_code=500, detail=detail)


@app.post("/api/chat/stream")
async def chat_stream(
    request: ChatRequest,
    user: UserInfo = Depends(require_auth),
):
    """Handle chat message with streaming progress events (SSE)."""
    try:
        get_session_manager().assert_session_owner(
            request.session_id,
            user.email,
        )
    except SessionOwnershipError:
        raise HTTPException(status_code=403, detail="Forbidden")

    orchestrator = get_orchestrator()
    cancellable = CancellableQuery(get_db())

    async def event_generator():
        try:
            async for event in orchestrator.handle_message_streaming(
                request, cancellable,
                user_email=user.email, user_role=user.role,
            ):
                event_type = event.get("event", "progress")

                if event_type == "progress":
                    payload = {
                        "step": event.get("step", ""),
                        "message": event.get("message", ""),
                        "progress": event.get("progress", 0),
                    }
                elif event_type == "complete":
                    payload = event.get("data", {})
                    if user.role != "super_user":
                        payload.pop("sql", None)
                        payload.pop("query_result", None)
                        payload.pop("sanity_checks", None)
                elif event_type == "cancelled":
                    payload = {
                        "message": event.get("message", "Query cancelled"),
                    }
                elif event_type == "auto_fix_countdown":
                    payload = dict(event.get("data", {}))
                    if user.role != "super_user":
                        payload.pop("failed_sql", None)
                        if "error_message" in payload:
                            payload["error_message"] = (
                                "Query encountered an error. Attempting auto-fix..."
                            )
                elif event_type == "auto_fix_new_attempt":
                    payload = dict(event.get("data", {}))
                    if user.role != "super_user":
                        payload.pop("failed_sql", None)
                        if "error_message" in payload:
                            payload["error_message"] = (
                                "Query encountered an error. Attempting auto-fix..."
                            )
                elif event_type == "error":
                    payload = {
                        "message": event.get("message", "Unknown error"),
                    }
                else:
                    payload = event

                data = json.dumps(
                    payload, ensure_ascii=False, default=str,
                )
                yield f"event: {event_type}\ndata: {data}\n\n"
        except Exception as e:
            logger.exception("Streaming error for user %s", user.email)
            err = json.dumps({"message": "Internal server error"})
            yield f"event: error\ndata: {err}\n\n"
        finally:
            cancellable.cancel()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
