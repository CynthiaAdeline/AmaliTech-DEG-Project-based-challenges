"""
Pulse-Check API — Watchdog Sentinel
Entry point: creates the FastAPI application and wires up the scheduler.

Run with:
    uvicorn src.main:app --reload
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI

from src.controllers.monitor_controller import router as monitor_router
from src.scheduler.monitor_scheduler import MonitorScheduler

scheduler = MonitorScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background scheduler on startup; stop it on shutdown."""
    await scheduler.start()
    yield
    await scheduler.stop()


app = FastAPI(
    title="Pulse-Check API — Watchdog Sentinel",
    description=(
        "A Dead Man's Switch API that tracks device health via stateful timers. "
        "Devices must continuously prove they are alive by sending heartbeats. "
        "If a device fails to do so within its configured timeout, an alert is triggered."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(monitor_router)


@app.get("/", tags=["Health"])
async def root():
    """Health check — confirms the service is running."""
    return {"service": "Pulse-Check API", "status": "running", "version": "1.0.0"}
