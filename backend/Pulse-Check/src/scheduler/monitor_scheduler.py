"""
Monitor Scheduler — background expiration checker.

Strategy: single polling loop that scans all monitors every POLL_INTERVAL
seconds and fires an alert for any ACTIVE monitor whose expiry has passed.

Why a polling loop instead of per-monitor asyncio.sleep() tasks?
  - One task to manage regardless of fleet size.
  - Alert deduplication is trivial: check status inside the lock.
  - Grace-period / retry logic lives in one place.
  - Trade-off: ~1 s resolution — acceptable for minute-scale timeouts.

Correctness guarantees:
  - The per-monitor lock is acquired before reading or mutating state,
    so a heartbeat arriving at the exact expiry boundary cannot race
    with the scheduler.
  - mark_down() sets status=DOWN inside the lock, so subsequent ticks
    skip the monitor via the fast-path status check — alert fires ONCE.
"""

import asyncio
import logging

from src.models.monitor_model import MonitorStatus
from src.services.monitor_service import fire_alert
from src.store.monitor_store import monitor_store
from src.utils.time_utils import utc_now

logger = logging.getLogger("pulse.scheduler")

POLL_INTERVAL: float = 1.0   # seconds between scans


class MonitorScheduler:
    """Manages the background expiration-check loop."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background polling loop (idempotent)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name="monitor-scheduler")
        logger.info("⏱  Scheduler started (poll interval: %ss)", POLL_INTERVAL)

    async def stop(self) -> None:
        """Stop the polling loop and wait for it to finish."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("⏱  Scheduler stopped.")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        while self._running:
            try:
                await self._tick()
            except Exception as exc:          # pragma: no cover
                logger.error("Scheduler error: %s", exc, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    async def _tick(self) -> None:
        """
        One scan pass: check every ACTIVE monitor for expiry.

        Double-check pattern:
          1. Fast path — skip non-ACTIVE monitors without locking.
          2. Acquire lock — re-check status (heartbeat may have just fired).
          3. Compare now >= expires_at and trigger alert if true.
        """
        now = utc_now()
        monitors = await monitor_store.all()

        for monitor in monitors:
            # Fast path: no lock needed for a status read
            if monitor.status != MonitorStatus.ACTIVE:
                continue

            async with monitor._lock:
                # Re-check inside the lock — heartbeat may have reset the timer
                if monitor.status != MonitorStatus.ACTIVE:
                    continue
                if monitor.expires_at is None:
                    continue
                if now >= monitor.expires_at:
                    monitor.mark_down()
                    fire_alert(monitor.id, monitor.alert_email)
                    logger.warning(
                        "Monitor '%s' → DOWN at %s",
                        monitor.id,
                        now.isoformat(),
                    )
