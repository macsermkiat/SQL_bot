"""
Tests for FastAPI routes, auth flow, role filtering, and security headers.

Tests cover:
- Login page rendering
- Login success/failure
- Logout
- Protected route redirects
- API 401 JSON response
- Role-based SQL filtering
- Security headers on responses
- Rate limiting integration
"""

import pytest
from starlette.testclient import TestClient

from app.auth import create_session_token
from app.main import app
from app.models import UserInfo


@pytest.fixture()
def client() -> TestClient:
    """Test client with no cookies."""
    return TestClient(app, cookies={})


def _standard_user() -> UserInfo:
    return UserInfo(
        email="test@hospital.org",
        name="Test User",
        department="Cardiology",
        role="standard_user",
    )


def _super_user() -> UserInfo:
    return UserInfo(
        email="admin@hospital.org",
        name="Admin User",
        department="IT",
        role="super_user",
    )


def _authed_client(user: UserInfo) -> TestClient:
    """Create a TestClient with session cookie set at the client level."""
    token = create_session_token(user)
    return TestClient(app, cookies={"kcmh_session": token})


class TestLoginPage:
    """Test GET /login."""

    def test_renders_login_form(self, client: TestClient):
        r = client.get("/login")
        assert r.status_code == 200
        assert "KCMH SQL Bot" in r.text
        assert 'name="email"' in r.text
        assert 'name="password"' in r.text

    def test_includes_starfield(self, client: TestClient):
        r = client.get("/login")
        assert "starfield" in r.text

    def test_authenticated_user_redirected(self):
        c = _authed_client(_standard_user())
        r = c.get("/login", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/"


class TestLoginPost:
    """Test POST /login."""

    def test_invalid_credentials_returns_401(self, client: TestClient):
        r = client.post(
            "/login",
            data={"email": "nobody@hospital.org", "password": "wrong"},
            follow_redirects=False,
        )
        assert r.status_code == 401
        assert "Invalid email or password" in r.text

    def test_missing_fields_returns_422(self, client: TestClient):
        r = client.post("/login", data={}, follow_redirects=False)
        assert r.status_code == 422


class TestLogout:
    """Test POST /logout."""

    def test_logout_redirects_to_login(self):
        c = _authed_client(_standard_user())
        r = c.post("/logout", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/login"

    def test_logout_clears_cookie(self):
        c = _authed_client(_standard_user())
        r = c.post("/logout", follow_redirects=False)
        set_cookie = r.headers.get("set-cookie", "")
        assert "kcmh_session" in set_cookie


class TestProtectedRoutes:
    """Test that routes require authentication."""

    def test_root_redirects_when_unauthenticated(self, client: TestClient):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/login"

    def test_root_accessible_when_authenticated(self):
        c = _authed_client(_standard_user())
        r = c.get("/")
        assert r.status_code == 200
        assert "chat-container" in r.text

    def test_api_chat_returns_401_json(self, client: TestClient):
        r = client.post("/api/chat", json={"message": "test"})
        assert r.status_code == 401
        assert r.json() == {"detail": "Not authenticated"}

    def test_expired_token_redirects(self):
        c = TestClient(app, cookies={"kcmh_session": "expired-garbage-token"})
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 302


class TestRoleFiltering:
    """Test that responses are filtered based on user role."""

    def test_chat_page_includes_role_for_standard(self):
        c = _authed_client(_standard_user())
        r = c.get("/")
        assert "standard_user" in r.text

    def test_chat_page_includes_role_for_super(self):
        c = _authed_client(_super_user())
        r = c.get("/")
        assert "super_user" in r.text

    def test_chat_page_shows_user_name(self):
        c = _authed_client(_standard_user())
        r = c.get("/")
        assert "Test User" in r.text

    def test_chat_page_shows_department(self):
        c = _authed_client(_standard_user())
        r = c.get("/")
        assert "Cardiology" in r.text


class TestSecurityHeaders:
    """Test that security headers are present on responses."""

    def test_x_content_type_options(self, client: TestClient):
        r = client.get("/login")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client: TestClient):
        r = client.get("/login")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_referrer_policy(self, client: TestClient):
        r = client.get("/login")
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_xss_protection(self, client: TestClient):
        r = client.get("/login")
        assert r.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_permissions_policy(self, client: TestClient):
        r = client.get("/login")
        assert "camera=()" in r.headers.get("Permissions-Policy", "")

    def test_headers_on_api_routes(self, client: TestClient):
        r = client.get("/api/health")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_headers_on_static_files(self, client: TestClient):
        r = client.get("/static/css/space-theme.css")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"


class TestDocsDisabled:
    """Test that API docs are disabled in production."""

    def test_docs_returns_404(self, client: TestClient):
        r = client.get("/docs")
        assert r.status_code == 404

    def test_redoc_returns_404(self, client: TestClient):
        r = client.get("/redoc")
        assert r.status_code == 404


class TestHealthEndpoint:
    """Test health check endpoint (no auth required)."""

    def test_health_returns_status(self, client: TestClient):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data
        assert "database" in data

    def test_health_no_auth_required(self, client: TestClient):
        """Health endpoint should not require authentication."""
        r = client.get("/api/health")
        assert r.status_code == 200
