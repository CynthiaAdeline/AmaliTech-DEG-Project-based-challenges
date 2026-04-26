"""
Monitor Service — all business logic lives here.

The controller layer calls these functions; it never touches the store or
the Monitor object directly. This keeps routes thin and logic testable.

Responsibilities:
  - Register / retrieve / delete monitors
  - Heartbeat: reset timer, auto-resume paused, revive down
  - Pause: freeze countdown
  - Alert: fire structured console log + simulated email
"""

import json
import logging
from typing import Optional

from src.models.monitor_model import Monitor, MonitorResponse, MonitorStatus
from src.store.monitor_store import monitor_store
from src.utils.time_utils import iso_now

logger = logging.getLogger("pulse.service")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

def fire_alert(device_id: str, alert_email: str) -> dict:
    """
    Trigger a structured alert for a device that has gone silent.

    Logs to console (required by spec) and simulates an email notification.
    Replace the body of this function to integrate a real email / webhook.

    Returns the alert payload dict for audit / testing purposes.
    """
    payload = {
        "ALERT": f"Device {device_id} is down!",
        "time": iso_now(),
        "device_id": device_id,
        "alert_email": alert_email,
    }

    # Required by spec: structured console output
    logger.critical("🚨 ALERT FIRED:\n%s", json.dumps(payload, indent=2))

    # Simulated email
    logger.info(
        "📧 [SIMULATED EMAIL] To: %s | Subject: CRITICAL — %s | Body: Alert at %s.",
        alert_email,
        payload["ALERT"],
        payload["time"],
    )

    return payload


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def register_monitor(
    id: str,
    timeout: int,
    alert_email: str,
) -> Optional[Monitor]:
    """
    Create and store a new monitor.

    Returns:
        The Monitor object if created successfully.
        None if a monitor with the same ID already exists.
    """
    monitor = Monitor(id=id, timeout=timeout, alert_email=alert_email)
    created = await monitor_store.create(monitor, overwrite=False)
    if not created:
        return None
    logger.info(
        "Monitor '%s' registered — timeout: %ss, email: %s",
        id, timeout, alert_email,
    )
    return monitor


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

async def heartbeat(monitor_id: str) -> Optional[tuple[Monitor, MonitorStatus]]:
    """
    Reset the countdown for an existing monitor.

    Behaviour by prior status:
      ACTIVE → timer reset, stays ACTIVE
      PAUSED → auto-resume + timer reset → ACTIVE
      DOWN   → revive + timer reset → ACTIVE

    Returns:
        (monitor, previous_status) on success.
        None if the monitor does not exist.
    """
    monitor = await monitor_store.get(monitor_id)
    if monitor is None:
        return None

    async with monitor._lock:
        prev_status = monitor.status
        monitor.reset_timer()

    logger.info(
        "Heartbeat for '%s' (was %s) → ACTIVE",
        monitor_id,
        prev_status.value,
    )
    return monitor, prev_status


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------

async def pause_monitor(monitor_id: str) -> Optional[tuple[Monitor, str]]:
    """
    Freeze the countdown for a monitor.

    Returns:
        (monitor, outcome) where outcome is one of:
          "paused"          — successfully paused
          "already_paused"  — was already paused (no-op)
          "conflict"        — monitor is DOWN, cannot pause
        None if the monitor does not exist.
    """
    monitor = await monitor_store.get(monitor_id)
    if monitor is None:
        return None

    async with monitor._lock:
        if monitor.status == MonitorStatus.DOWN:
            return monitor, "conflict"
        if monitor.status == MonitorStatus.PAUSED:
            return monitor, "already_paused"
        monitor.pause()

    logger.info("Monitor '%s' paused.", monitor_id)
    return monitor, "paused"


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_monitor(monitor_id: str) -> Optional[Monitor]:
    """Return the monitor for the given ID, or None."""
    return await monitor_store.get(monitor_id)


async def list_monitors() -> list[MonitorResponse]:
    """Return response objects for all registered monitors."""
    monitors = await monitor_store.all()
    return [m.to_response() for m in monitors]


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_monitor(monitor_id: str) -> bool:
    """
    Remove a monitor permanently.

    Returns True if deleted, False if not found.
    """
    deleted = await monitor_store.delete(monitor_id)
    if deleted:
        logger.info("Monitor '%s' deleted.", monitor_id)
    return deleted
