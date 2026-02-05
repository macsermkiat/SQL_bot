"""
Authentication module: CSV-based user loading, session management, role assignment.
"""

from __future__ import annotations

import csv
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import Cookie, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import get_settings
from app.models import UserInfo

logger = logging.getLogger(__name__)


class UserStore:
    """Loads users from CSV and super_user list from JSON."""

    def __init__(self, csv_path: Path, super_users_path: Path) -> None:
        self._users: dict[str, dict[str, str]] = {}
        self._super_users: set[str] = set()
        self._load_users(csv_path)
        self._load_super_users(super_users_path)

    def _load_users(self, csv_path: Path) -> None:
        """Load users from CSV. Email is key, ID is password."""
        if not csv_path.exists():
            logger.error("Users CSV not found: %s", csv_path)
            return

        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("E-mail", "").strip().lower()
                if not email:
                    continue
                self._users[email] = {
                    "name": row.get("NAME", "").strip(),
                    "id": row.get("ID", "").strip(),
                    "department": row.get("Department", "").strip(),
                }

        logger.info("Loaded %d users from CSV", len(self._users))

    def _load_super_users(self, path: Path) -> None:
        """Load super user email list from JSON."""
        if not path.exists():
            logger.warning("Super users file not found: %s", path)
            return

        try:
            with open(path, encoding="utf-8") as f:
                data = json.loads(f.read())
            emails = data.get("super_users", [])
            self._super_users = {e.strip().lower() for e in emails}
            logger.info("Loaded %d super users", len(self._super_users))
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Failed to load super users: %s", exc)

    def verify(self, email: str, password: str) -> UserInfo | None:
        """Verify credentials and return UserInfo or None."""
        email_lower = email.strip().lower()
        user = self._users.get(email_lower)
        if user is None:
            return None

        if user["id"] != password.strip():
            return None

        role = (
            "super_user"
            if email_lower in self._super_users
            else "standard_user"
        )

        return UserInfo(
            email=email_lower,
            name=user["name"],
            department=user["department"],
            role=role,
        )

    @property
    def user_count(self) -> int:
        return len(self._users)


_store: UserStore | None = None


def get_user_store() -> UserStore:
    """Get or create the global user store."""
    global _store
    if _store is None:
        settings = get_settings()
        _store = UserStore(
            csv_path=settings.users_csv_path,
            super_users_path=settings.super_users_path,
        )
    return _store


def _get_serializer() -> URLSafeTimedSerializer:
    """Get the session cookie serializer."""
    settings = get_settings()
    return URLSafeTimedSerializer(settings.secret_key)


def create_session_token(user: UserInfo) -> str:
    """Create a signed session token containing user info."""
    serializer = _get_serializer()
    return serializer.dumps({
        "email": user.email,
        "name": user.name,
        "department": user.department,
        "role": user.role,
    })


def decode_session_token(token: str) -> UserInfo | None:
    """Decode and verify a session token. Returns None if invalid/expired."""
    settings = get_settings()
    serializer = _get_serializer()
    try:
        data: dict[str, Any] = serializer.loads(
            token,
            max_age=settings.session_max_age,
        )
        return UserInfo(
            email=data["email"],
            name=data["name"],
            department=data["department"],
            role=data["role"],
        )
    except SignatureExpired:
        logger.info("Session token expired")
        return None
    except BadSignature:
        logger.warning("Invalid session token signature")
        return None
    except (KeyError, TypeError) as exc:
        logger.warning("Malformed session token: %s", exc)
        return None


def get_current_user_from_cookie(request: Request) -> UserInfo | None:
    """Extract and validate user from session cookie. Returns None if not authenticated."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        return None
    return decode_session_token(token)


async def require_auth(request: Request) -> UserInfo:
    """FastAPI dependency: require authenticated user or raise 401."""
    user = get_current_user_from_cookie(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user
