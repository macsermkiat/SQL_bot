"""
In-memory session management.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from app.models import Message, Session


class SessionOwnershipError(Exception):
    """Raised when a user tries to reuse another user's chat session."""


class SessionManager:
    """Manages chat sessions in memory."""

    def __init__(self, session_ttl_hours: int = 24) -> None:
        self._sessions: dict[str, Session] = {}
        self._session_ttl = timedelta(hours=session_ttl_hours)

    @staticmethod
    def _normalize_owner(owner_email: str | None) -> str | None:
        return owner_email.strip().lower() if owner_email else None

    def create_session(self, owner_email: str | None = None) -> Session:
        """Create a new session."""
        session_id = str(uuid.uuid4())
        session = Session(
            session_id=session_id,
            owner_email=self._normalize_owner(owner_email),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        """Get session by ID, or None if not found/expired."""
        session = self._sessions.get(session_id)
        if session is None:
            return None

        # Check if expired
        if datetime.now() - session.last_activity > self._session_ttl:
            del self._sessions[session_id]
            return None

        return session

    def _assert_owner(
        self,
        session: Session,
        owner_email: str | None,
    ) -> None:
        owner = self._normalize_owner(owner_email)
        if session.owner_email is None:
            session.owner_email = owner
            return
        if owner is not None and session.owner_email != owner:
            raise SessionOwnershipError("Chat session belongs to another user")

    def assert_session_owner(
        self,
        session_id: str | None,
        owner_email: str | None,
    ) -> None:
        """Validate ownership for an existing session without creating one."""
        if not session_id:
            return
        session = self.get_session(session_id)
        if session is not None:
            self._assert_owner(session, owner_email)

    def get_or_create_session(
        self,
        session_id: str | None,
        owner_email: str | None = None,
    ) -> Session:
        """Get existing session or create new one."""
        if session_id:
            session = self.get_session(session_id)
            if session:
                self._assert_owner(session, owner_email)
                return session

        return self.create_session(owner_email=owner_email)

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        owner_email: str | None = None,
        **metadata: Any,
    ) -> Message | None:
        """Add message to session."""
        session = self.get_session(session_id)
        if session is None:
            return None
        self._assert_owner(session, owner_email)

        return session.add_message(role, content, **metadata)

    def get_conversation_history(
        self,
        session_id: str,
        max_messages: int = 10,
        owner_email: str | None = None,
    ) -> list[dict[str, str]]:
        """Get conversation history for LLM context."""
        session = self.get_session(session_id)
        if session is None:
            return []
        self._assert_owner(session, owner_email)

        messages = session.messages[-max_messages:]
        return [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]

    def cleanup_expired(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        now = datetime.now()
        expired = [
            sid for sid, session in self._sessions.items()
            if now - session.last_activity > self._session_ttl
        ]
        for sid in expired:
            del self._sessions[sid]
        return len(expired)

    def session_count(self) -> int:
        """Get number of active sessions."""
        return len(self._sessions)


# Global session manager
_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """Get global session manager instance."""
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
