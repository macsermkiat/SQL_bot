"""
In-memory rate limiter for login endpoint.
Tracks failed attempts per IP and enforces cooldown after threshold.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _AttemptRecord:
    """Tracks login attempts for a single IP."""

    failures: int = 0
    locked_until: float = 0.0
    timestamps: list[float] = field(default_factory=list)


class LoginRateLimiter:
    """Rate limiter that blocks IPs after too many failed login attempts."""

    def __init__(
        self,
        max_failures: int = 5,
        lockout_seconds: int = 300,
        window_seconds: int = 600,
    ) -> None:
        self._max_failures = max_failures
        self._lockout_seconds = lockout_seconds
        self._window_seconds = window_seconds
        self._attempts: dict[str, _AttemptRecord] = {}

    def is_blocked(self, ip: str) -> bool:
        """Check if an IP is currently blocked."""
        record = self._attempts.get(ip)
        if record is None:
            return False

        now = time.monotonic()

        # If locked out and still within lockout period
        if record.locked_until > now:
            return True

        # If lockout expired, reset
        if record.locked_until > 0 and record.locked_until <= now:
            del self._attempts[ip]
            return False

        return False

    def remaining_seconds(self, ip: str) -> int:
        """Seconds remaining in lockout. Returns 0 if not locked."""
        record = self._attempts.get(ip)
        if record is None:
            return 0

        now = time.monotonic()
        if record.locked_until > now:
            return int(record.locked_until - now) + 1
        return 0

    def record_failure(self, ip: str) -> None:
        """Record a failed login attempt."""
        now = time.monotonic()

        if ip not in self._attempts:
            self._attempts[ip] = _AttemptRecord()

        record = self._attempts[ip]

        # Prune old timestamps outside the window
        cutoff = now - self._window_seconds
        record.timestamps = [t for t in record.timestamps if t > cutoff]

        record.timestamps.append(now)
        record.failures = len(record.timestamps)

        if record.failures >= self._max_failures:
            record.locked_until = now + self._lockout_seconds

    def record_success(self, ip: str) -> None:
        """Clear attempts on successful login."""
        self._attempts.pop(ip, None)

    def cleanup(self) -> int:
        """Remove expired records. Returns count removed."""
        now = time.monotonic()
        expired = [
            ip
            for ip, rec in self._attempts.items()
            if rec.locked_until > 0 and rec.locked_until <= now
        ]
        for ip in expired:
            del self._attempts[ip]
        return len(expired)


# Global instance
_limiter: LoginRateLimiter | None = None


def get_login_limiter() -> LoginRateLimiter:
    """Get or create the global login rate limiter."""
    global _limiter
    if _limiter is None:
        _limiter = LoginRateLimiter()
    return _limiter
