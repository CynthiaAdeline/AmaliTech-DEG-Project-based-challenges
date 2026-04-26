"""
Data models for the Pulse-Check API.

Contains:
- MonitorStatus  — enum for the three possible states
- CreateMonitorRequest — Pydantic schema for POST /monitors body
- MonitorResponse      — Pydantic schema returned by all endpoints
- MessageResponse      — simple {"message": "..."} wrapper
- Monitor              — internal state-machine object (lives in memory)
"""

import asyncio
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MonitorStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DOWN   = "down"


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class CreateMonitorRequest(BaseModel):
    id: str = Field(..., min_length=1, description="Unique device identifier")
    timeout: int = Field(..., gt=0, description="Countdown duration in seconds")
    alert_email: EmailStr = Field(..., description="Email to notify on alert")

    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "device-123",
                "timeout": 60,
                "alert_email": "admin@critmon.com",
            }
        }
    }


class MonitorResponse(BaseModel):
    id: str
    timeout: int
    status: MonitorStatus
    alert_email: str
    expires_at: Optional[datetime]
    remaining_seconds: Optional[float]
    created_at: datetime
    alert_count: int

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Internal monitor state (not a DB model — lives in memory)
# ---------------------------------------------------------------------------

class Monitor:
    """
    Represents a single device monitor as a finite state machine.

    Transitions:
        ACTIVE  ──heartbeat──►  ACTIVE   (timer reset)
        ACTIVE  ──pause──────►  PAUSED   (timer frozen)
        ACTIVE  ──timeout────►  DOWN     (alert fired exactly once)
        PAUSED  ──heartbeat──►  ACTIVE   (auto-resume + timer reset)
        PAUSED  ──pause──────►  PAUSED   (no-op)
        DOWN    ──heartbeat──►  ACTIVE   (revive + timer reset)
        DOWN    ──pause──────►  409      (must heartbeat first)
    """

    def __init__(self, id: str, timeout: int, alert_email: str):
        self.id = id
        self.timeout = timeout
        self.alert_email = alert_email
        self.status: MonitorStatus = MonitorStatus.ACTIVE
        self.created_at: datetime = datetime.now(timezone.utc)
        self.expires_at: Optional[datetime] = None
        self.alert_count: int = 0

        # Per-instance lock prevents race conditions on concurrent heartbeats
        self._lock: asyncio.Lock = asyncio.Lock()

        self._set_expiry()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_expiry(self) -> None:
        """Push expiry forward by the full timeout from now."""
        self.expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.timeout)

    # ------------------------------------------------------------------
    # State transitions  (always called while holding self._lock)
    # ------------------------------------------------------------------

    def reset_timer(self) -> None:
        """Reset expiry to now + timeout and set status to ACTIVE."""
        self._set_expiry()
        self.status = MonitorStatus.ACTIVE

    def pause(self) -> None:
        """Freeze the countdown. Status → PAUSED, expiry cleared."""
        self.status = MonitorStatus.PAUSED
        self.expires_at = None

    def mark_down(self) -> None:
        """Mark monitor as DOWN and increment the alert counter."""
        self.status = MonitorStatus.DOWN
        self.expires_at = None
        self.alert_count += 1

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def remaining_seconds(self) -> Optional[float]:
        if self.status != MonitorStatus.ACTIVE or self.expires_at is None:
            return None
        delta = (self.expires_at - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, delta)

    def to_response(self) -> MonitorResponse:
        return MonitorResponse(
            id=self.id,
            timeout=self.timeout,
            status=self.status,
            alert_email=self.alert_email,
            expires_at=self.expires_at,
            remaining_seconds=self.remaining_seconds,
            created_at=self.created_at,
            alert_count=self.alert_count,
        )
