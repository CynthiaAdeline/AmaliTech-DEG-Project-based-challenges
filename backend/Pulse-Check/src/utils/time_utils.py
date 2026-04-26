"""
Time utility helpers for the Pulse-Check API.

Centralises all datetime/timezone operations so the rest of the codebase
never has to import datetime directly — making it easy to mock in tests
or swap to a different clock source.
"""

from datetime import datetime, timedelta, timezone


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


def utc_after(seconds: int | float) -> datetime:
    """Return a UTC datetime `seconds` from now."""
    return utc_now() + timedelta(seconds=seconds)


def is_expired(expires_at: datetime | None) -> bool:
    """
    Return True if `expires_at` is in the past (or None).

    A None expiry is treated as already expired so callers can use this
    safely without a None-check.
    """
    if expires_at is None:
        return True
    return utc_now() >= expires_at


def remaining(expires_at: datetime | None) -> float | None:
    """
    Return seconds remaining until `expires_at`, or None if not applicable.

    Never returns a negative value — clamps to 0.0.
    """
    if expires_at is None:
        return None
    delta = (expires_at - utc_now()).total_seconds()
    return max(0.0, delta)


def iso_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return utc_now().isoformat()
