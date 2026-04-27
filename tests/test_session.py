"""Tests for chat session ownership."""

from __future__ import annotations

import pytest

from app.session import SessionManager, SessionOwnershipError


def test_same_user_can_continue_session() -> None:
    manager = SessionManager()
    session = manager.get_or_create_session(None, owner_email="Alice@Example.org")

    same = manager.get_or_create_session(
        session.session_id,
        owner_email="alice@example.org",
    )

    assert same.session_id == session.session_id


def test_cross_user_session_rejected() -> None:
    manager = SessionManager()
    session = manager.get_or_create_session(None, owner_email="alice@example.org")

    with pytest.raises(SessionOwnershipError):
        manager.get_or_create_session(
            session.session_id,
            owner_email="bob@example.org",
        )


def test_unknown_session_creates_new_owned_session() -> None:
    manager = SessionManager()

    session = manager.get_or_create_session(
        "not-a-real-session",
        owner_email="alice@example.org",
    )

    assert session.session_id != "not-a-real-session"
    assert session.owner_email == "alice@example.org"
