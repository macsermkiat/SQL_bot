"""Tests for FastAPI lifespan background maintenance."""

import asyncio
import os
from contextlib import suppress
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from app.main import _periodic_login_limiter_cleanup


@pytest.mark.asyncio
async def test_periodic_login_limiter_cleanup_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limiter = MagicMock()
    monkeypatch.setattr("app.main.get_login_limiter", lambda: limiter)
    task = asyncio.create_task(_periodic_login_limiter_cleanup(0))

    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert limiter.cleanup.called
