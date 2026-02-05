"""
Tests for login rate limiting.

Tests cover:
- Failure counting and lockout trigger
- Remaining seconds calculation
- Success clears failures
- Cleanup of expired records
- Different IPs are independent
"""

import time
from unittest.mock import patch

import pytest

from app.rate_limit import LoginRateLimiter


@pytest.fixture()
def limiter() -> LoginRateLimiter:
    """Create a rate limiter with low thresholds for testing."""
    return LoginRateLimiter(
        max_failures=3,
        lockout_seconds=60,
        window_seconds=120,
    )


class TestFailureCounting:
    """Test that failures are counted and lockout triggers correctly."""

    def test_not_blocked_initially(self, limiter: LoginRateLimiter):
        assert not limiter.is_blocked("1.2.3.4")

    def test_not_blocked_below_threshold(self, limiter: LoginRateLimiter):
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        assert not limiter.is_blocked("1.2.3.4")

    def test_blocked_at_threshold(self, limiter: LoginRateLimiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4")

    def test_blocked_above_threshold(self, limiter: LoginRateLimiter):
        for _ in range(5):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4")


class TestRemainingSeconds:
    """Test lockout remaining time calculation."""

    def test_zero_when_not_blocked(self, limiter: LoginRateLimiter):
        assert limiter.remaining_seconds("1.2.3.4") == 0

    def test_positive_when_blocked(self, limiter: LoginRateLimiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        remaining = limiter.remaining_seconds("1.2.3.4")
        assert remaining > 0
        assert remaining <= 61  # lockout_seconds + 1

    def test_zero_for_unknown_ip(self, limiter: LoginRateLimiter):
        assert limiter.remaining_seconds("9.9.9.9") == 0


class TestSuccessClearsFailures:
    """Test that successful login clears the failure record."""

    def test_success_clears_record(self, limiter: LoginRateLimiter):
        limiter.record_failure("1.2.3.4")
        limiter.record_failure("1.2.3.4")
        limiter.record_success("1.2.3.4")
        assert not limiter.is_blocked("1.2.3.4")

    def test_success_on_unknown_ip_no_error(self, limiter: LoginRateLimiter):
        limiter.record_success("9.9.9.9")  # should not raise


class TestIPIsolation:
    """Test that rate limiting is per-IP."""

    def test_different_ips_independent(self, limiter: LoginRateLimiter):
        for _ in range(3):
            limiter.record_failure("1.1.1.1")
        assert limiter.is_blocked("1.1.1.1")
        assert not limiter.is_blocked("2.2.2.2")

    def test_one_ip_success_does_not_affect_other(self, limiter: LoginRateLimiter):
        limiter.record_failure("1.1.1.1")
        limiter.record_failure("2.2.2.2")
        limiter.record_success("1.1.1.1")
        # 2.2.2.2 still has its failure count
        limiter.record_failure("2.2.2.2")
        limiter.record_failure("2.2.2.2")
        assert limiter.is_blocked("2.2.2.2")
        assert not limiter.is_blocked("1.1.1.1")


class TestCleanup:
    """Test cleanup of expired lockout records."""

    def test_cleanup_removes_expired(self, limiter: LoginRateLimiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4")

        # Simulate time passing beyond lockout
        record = limiter._attempts["1.2.3.4"]
        record.locked_until = time.monotonic() - 1  # expired

        removed = limiter.cleanup()
        assert removed == 1
        assert not limiter.is_blocked("1.2.3.4")

    def test_cleanup_keeps_active(self, limiter: LoginRateLimiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        removed = limiter.cleanup()
        assert removed == 0
        assert limiter.is_blocked("1.2.3.4")


class TestLockoutExpiry:
    """Test that lockout expires after the configured duration."""

    def test_unblocked_after_expiry(self, limiter: LoginRateLimiter):
        for _ in range(3):
            limiter.record_failure("1.2.3.4")
        assert limiter.is_blocked("1.2.3.4")

        # Simulate lockout expiry
        record = limiter._attempts["1.2.3.4"]
        record.locked_until = time.monotonic() - 1

        assert not limiter.is_blocked("1.2.3.4")
        # Record should be cleaned up
        assert "1.2.3.4" not in limiter._attempts


class TestDefaultConfiguration:
    """Test default configuration values."""

    def test_default_max_failures(self):
        lim = LoginRateLimiter()
        # Default is 5 failures
        for _ in range(4):
            lim.record_failure("x")
        assert not lim.is_blocked("x")
        lim.record_failure("x")
        assert lim.is_blocked("x")
