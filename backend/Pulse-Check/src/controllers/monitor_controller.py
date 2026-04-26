"""
Monitor Controller — API layer (routes only).

Each route delegates immediately to the service layer.
No business logic lives here: just HTTP plumbing (parse input,
call service, map result to HTTP response / error).

Routes:
  POST   /monitors                — Register a new monitor
  POST   /monitors/{id}/heartbeat — Reset the countdown
  POST   /monitors/{id}/pause     — Freeze the countdown
  GET    /monitors/{id}           — Inspect monitor status  [Developer's Choice]
  GET    /monitors                — List all monitors       [Developer's Choice]
  DELETE /monitors/{id}           — Remove a monitor        [Developer's Choice]
"""

import logging
from fastapi import APIRouter, HTTPException, status

from src.models.monitor_model import (
    CreateMonitorRequest,
    MessageResponse,
    MonitorResponse,
    MonitorStatus,
)
from src.services import monitor_service

logger = logging.getLogger("pulse.controller")
router = APIRouter(prefix="/monitors", tags=["Monitors"])


# ---------------------------------------------------------------------------
# POST /monitors — Register
# ---------------------------------------------------------------------------

@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=MonitorResponse,
    summary="Register a new monitor",
)
async def create_monitor(body: CreateMonitorRequest):
    """
    Create a new monitor for a device.

    - Starts the countdown timer immediately.
    - Rejects duplicate IDs with 409 Conflict.
    - `timeout` must be > 0 seconds.
    - `alert_email` must be a valid email address.
    """
    monitor = await monitor_service.register_monitor(
        id=body.id,
        timeout=body.timeout,
        alert_email=body.alert_email,
    )
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Monitor '{body.id}' already exists. DELETE it first or use a unique ID.",
        )
    return monitor.to_response()


# ---------------------------------------------------------------------------
# POST /monitors/{id}/heartbeat — Heartbeat
# ---------------------------------------------------------------------------

@router.post(
    "/{monitor_id}/heartbeat",
    response_model=MessageResponse,
    summary="Send a heartbeat to reset the countdown",
)
async def heartbeat(monitor_id: str):
    """
    Reset the countdown for an existing monitor.

    - ACTIVE  → timer reset, stays ACTIVE.
    - PAUSED  → auto-resumes + timer reset → ACTIVE.
    - DOWN    → revives the monitor + timer reset → ACTIVE.
    - Missing → 404 Not Found.

    Safe under rapid concurrent requests (per-monitor asyncio lock).
    """
    result = await monitor_service.heartbeat(monitor_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )

    _, prev_status = result
    action_map = {
        MonitorStatus.ACTIVE: "Timer reset",
        MonitorStatus.PAUSED: "Monitor auto-resumed and timer reset",
        MonitorStatus.DOWN:   "Monitor revived and timer reset",
    }
    msg = action_map.get(prev_status, "Timer reset")
    return {"message": f"{msg} for monitor '{monitor_id}'."}


# ---------------------------------------------------------------------------
# POST /monitors/{id}/pause — Pause
# ---------------------------------------------------------------------------

@router.post(
    "/{monitor_id}/pause",
    response_model=MessageResponse,
    summary="Pause (freeze) the countdown",
)
async def pause_monitor(monitor_id: str):
    """
    Freeze the countdown for a monitor.

    - ACTIVE → timer frozen → PAUSED.
    - PAUSED → no-op, returns 200 with info message.
    - DOWN   → 409 Conflict (send a heartbeat to revive first).
    - Missing → 404 Not Found.
    """
    result = await monitor_service.pause_monitor(monitor_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )

    _, outcome = result
    if outcome == "conflict":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Monitor '{monitor_id}' is DOWN. Send a heartbeat to revive it first.",
        )
    if outcome == "already_paused":
        return {"message": f"Monitor '{monitor_id}' is already paused."}

    return {"message": f"Monitor '{monitor_id}' paused. No alerts will fire until resumed."}


# ---------------------------------------------------------------------------
# GET /monitors/{id} — Status  [Developer's Choice]
# ---------------------------------------------------------------------------

@router.get(
    "/{monitor_id}",
    response_model=MonitorResponse,
    summary="Get monitor status",
)
async def get_monitor(monitor_id: str):
    """
    Retrieve the current state of a monitor, including remaining seconds.

    Developer's Choice: gives operators live visibility into any device
    without having to read logs.
    """
    monitor = await monitor_service.get_monitor(monitor_id)
    if monitor is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )
    return monitor.to_response()


# ---------------------------------------------------------------------------
# GET /monitors — List all  [Developer's Choice]
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=list[MonitorResponse],
    summary="List all monitors",
)
async def list_monitors():
    """
    Return a summary of every registered monitor.

    Developer's Choice: enables fleet-wide dashboards and ops tooling.
    """
    return await monitor_service.list_monitors()


# ---------------------------------------------------------------------------
# DELETE /monitors/{id} — Remove  [Developer's Choice]
# ---------------------------------------------------------------------------

@router.delete(
    "/{monitor_id}",
    response_model=MessageResponse,
    summary="Delete a monitor",
)
async def delete_monitor(monitor_id: str):
    """
    Permanently remove a monitor from the system.

    Developer's Choice: allows clean decommissioning of devices and
    prevents the in-memory store from growing indefinitely.
    """
    deleted = await monitor_service.delete_monitor(monitor_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Monitor '{monitor_id}' not found.",
        )
    return {"message": f"Monitor '{monitor_id}' has been deleted."}
