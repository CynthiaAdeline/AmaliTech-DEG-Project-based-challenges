"""
In-memory monitor store with async-safe access.

Two levels of locking:
  - _registry_lock  : guards the dict itself (create / delete / list)
  - monitor._lock   : guards per-monitor state transitions (heartbeat, pause, expiry)

This separation means concurrent heartbeats for *different* devices never
block each other, while concurrent heartbeats for the *same* device are
safely serialised through the per-monitor lock.
"""

import asyncio
from typing import Dict, Optional

from src.models.monitor_model import Monitor


class MonitorStore:
    def __init__(self) -> None:
        self._monitors: Dict[str, Monitor] = {}
        self._registry_lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(self, monitor: Monitor, overwrite: bool = False) -> bool:
        """
        Add a monitor to the store.

        Returns:
            True  — monitor was stored.
            False — duplicate ID and overwrite=False; nothing changed.
        """
        async with self._registry_lock:
            if monitor.id in self._monitors and not overwrite:
                return False
            self._monitors[monitor.id] = monitor
            return True

    async def get(self, monitor_id: str) -> Optional[Monitor]:
        """Return the monitor for the given ID, or None if not found."""
        async with self._registry_lock:
            return self._monitors.get(monitor_id)

    async def delete(self, monitor_id: str) -> bool:
        """
        Remove a monitor from the store.

        Returns:
            True  — monitor was deleted.
            False — monitor not found.
        """
        async with self._registry_lock:
            if monitor_id not in self._monitors:
                return False
            del self._monitors[monitor_id]
            return True

    async def all(self) -> list[Monitor]:
        """Return a snapshot list of all monitors."""
        async with self._registry_lock:
            return list(self._monitors.values())

    async def count(self) -> int:
        """Return the number of registered monitors."""
        async with self._registry_lock:
            return len(self._monitors)


# ---------------------------------------------------------------------------
# Singleton — shared across the entire application
# ---------------------------------------------------------------------------
monitor_store = MonitorStore()
