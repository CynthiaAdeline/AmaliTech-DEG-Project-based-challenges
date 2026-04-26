"""
Tests for the Pulse-Check API.

Covers:
- Monitor registration (happy path, duplicate, validation)
- Heartbeat (active, paused, down, missing)
- Pause (active, already paused, down, missing)
- Status / list / delete endpoints  (Developer's Choice)
- Timer expiry and alert firing
- Alert fires exactly once
- Concurrency: 50 simultaneous heartbeats
"""

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.store.monitor_store import monitor_store


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
async def clear_store():
    """Wipe the store before and after every test for full isolation."""
    for m in await monitor_store.all():
        await monitor_store.delete(m.id)
    yield
    for m in await monitor_store.all():
        await monitor_store.delete(m.id)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_monitor(client):
    resp = await client.post("/monitors", json={
        "id": "dev-1", "timeout": 60, "alert_email": "a@b.com"
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "dev-1"
    assert data["status"] == "active"
    assert data["timeout"] == 60
    assert data["remaining_seconds"] is not None
    assert data["remaining_seconds"] <= 60


@pytest.mark.asyncio
async def test_create_duplicate_monitor(client):
    payload = {"id": "dev-dup", "timeout": 30, "alert_email": "a@b.com"}
    await client.post("/monitors", json=payload)
    resp = await client.post("/monitors", json=payload)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_create_monitor_invalid_timeout(client):
    resp = await client.post("/monitors", json={
        "id": "dev-bad", "timeout": 0, "alert_email": "a@b.com"
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_monitor_invalid_email(client):
    resp = await client.post("/monitors", json={
        "id": "dev-bad", "timeout": 10, "alert_email": "not-an-email"
    })
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_active_monitor(client):
    await client.post("/monitors", json={
        "id": "dev-hb", "timeout": 60, "alert_email": "a@b.com"
    })
    resp = await client.post("/monitors/dev-hb/heartbeat")
    assert resp.status_code == 200
    assert "dev-hb" in resp.json()["message"]


@pytest.mark.asyncio
async def test_heartbeat_missing_monitor(client):
    resp = await client.post("/monitors/ghost/heartbeat")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_heartbeat_paused_monitor_auto_resumes(client):
    await client.post("/monitors", json={
        "id": "dev-pause-hb", "timeout": 60, "alert_email": "a@b.com"
    })
    await client.post("/monitors/dev-pause-hb/pause")
    assert (await client.get("/monitors/dev-pause-hb")).json()["status"] == "paused"

    resp = await client.post("/monitors/dev-pause-hb/heartbeat")
    assert resp.status_code == 200
    assert (await client.get("/monitors/dev-pause-hb")).json()["status"] == "active"


@pytest.mark.asyncio
async def test_heartbeat_down_monitor_revives(client):
    """Heartbeat on a DOWN monitor should revive it to ACTIVE."""
    await client.post("/monitors", json={
        "id": "dev-down-hb", "timeout": 60, "alert_email": "a@b.com"
    })
    monitor = await monitor_store.get("dev-down-hb")
    async with monitor._lock:
        monitor.mark_down()

    resp = await client.post("/monitors/dev-down-hb/heartbeat")
    assert resp.status_code == 200
    assert (await client.get("/monitors/dev-down-hb")).json()["status"] == "active"


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pause_active_monitor(client):
    await client.post("/monitors", json={
        "id": "dev-p", "timeout": 60, "alert_email": "a@b.com"
    })
    resp = await client.post("/monitors/dev-p/pause")
    assert resp.status_code == 200

    data = (await client.get("/monitors/dev-p")).json()
    assert data["status"] == "paused"
    assert data["remaining_seconds"] is None


@pytest.mark.asyncio
async def test_pause_already_paused(client):
    await client.post("/monitors", json={
        "id": "dev-pp", "timeout": 60, "alert_email": "a@b.com"
    })
    await client.post("/monitors/dev-pp/pause")
    resp = await client.post("/monitors/dev-pp/pause")
    assert resp.status_code == 200
    assert "already paused" in resp.json()["message"]


@pytest.mark.asyncio
async def test_pause_down_monitor_returns_409(client):
    await client.post("/monitors", json={
        "id": "dev-pd", "timeout": 60, "alert_email": "a@b.com"
    })
    monitor = await monitor_store.get("dev-pd")
    async with monitor._lock:
        monitor.mark_down()

    resp = await client.post("/monitors/dev-pd/pause")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_pause_missing_monitor(client):
    resp = await client.post("/monitors/ghost/pause")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Status / List / Delete  (Developer's Choice)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_monitor_status(client):
    await client.post("/monitors", json={
        "id": "dev-s", "timeout": 60, "alert_email": "a@b.com"
    })
    resp = await client.get("/monitors/dev-s")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "dev-s"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_get_missing_monitor(client):
    resp = await client.get("/monitors/ghost")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_monitors(client):
    await client.post("/monitors", json={"id": "d1", "timeout": 60, "alert_email": "a@b.com"})
    await client.post("/monitors", json={"id": "d2", "timeout": 60, "alert_email": "a@b.com"})
    resp = await client.get("/monitors")
    assert resp.status_code == 200
    ids = [m["id"] for m in resp.json()]
    assert "d1" in ids
    assert "d2" in ids


@pytest.mark.asyncio
async def test_delete_monitor(client):
    await client.post("/monitors", json={
        "id": "dev-del", "timeout": 60, "alert_email": "a@b.com"
    })
    assert (await client.delete("/monitors/dev-del")).status_code == 200
    assert (await client.get("/monitors/dev-del")).status_code == 404


@pytest.mark.asyncio
async def test_delete_missing_monitor(client):
    resp = await client.delete("/monitors/ghost")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Timer expiry and alert
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_timer_expiry_marks_monitor_down():
    """Monitor with 1 s timeout must transition to DOWN after the scheduler ticks."""
    from src.scheduler.monitor_scheduler import MonitorScheduler
    from src.models.monitor_model import Monitor

    engine = MonitorScheduler()
    m = Monitor(id="dev-expire", timeout=1, alert_email="a@b.com")
    await monitor_store.create(m, overwrite=True)

    await engine.start()
    await asyncio.sleep(2.5)
    await engine.stop()

    expired = await monitor_store.get("dev-expire")
    assert expired is not None
    assert expired.status.value == "down"
    assert expired.alert_count == 1


@pytest.mark.asyncio
async def test_alert_fires_only_once():
    """Alert count must be exactly 1 even after multiple scheduler ticks."""
    from src.scheduler.monitor_scheduler import MonitorScheduler
    from src.models.monitor_model import Monitor

    engine = MonitorScheduler()
    m = Monitor(id="dev-once", timeout=1, alert_email="a@b.com")
    await monitor_store.create(m, overwrite=True)

    await engine.start()
    await asyncio.sleep(3.5)
    await engine.stop()

    monitor = await monitor_store.get("dev-once")
    assert monitor.alert_count == 1


# ---------------------------------------------------------------------------
# Concurrency: rapid heartbeats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_heartbeats_are_safe(client):
    """50 simultaneous heartbeats must not corrupt state."""
    await client.post("/monitors", json={
        "id": "dev-concurrent", "timeout": 60, "alert_email": "a@b.com"
    })

    results = await asyncio.gather(
        *[client.post("/monitors/dev-concurrent/heartbeat") for _ in range(50)]
    )
    assert all(r.status_code == 200 for r in results)
    assert (await client.get("/monitors/dev-concurrent")).json()["status"] == "active"
