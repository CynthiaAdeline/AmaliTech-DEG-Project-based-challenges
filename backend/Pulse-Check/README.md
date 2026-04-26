=======
# Pulse-Check API — Watchdog Sentinel

A **Dead Man's Switch** backend service that tracks device health using stateful timers.  
Devices must continuously prove they are alive by sending heartbeats. If a device goes silent past its configured timeout, the system automatically detects the failure and fires an alert — no human intervention required.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Architecture Diagram](#2-architecture-diagram)
3. [Setup Instructions](#3-setup-instructions)
4. [API Documentation](#4-api-documentation)
5. [Core Logic Explanation](#5-core-logic-explanation)
6. [Developer's Choice Feature](#6-developers-choice-feature)
7. [Key Design Decisions](#7-key-design-decisions)

---

## 1. Project Overview

### The Problem

CritMon Servers Inc. monitors remote solar farms and unmanned weather stations in areas with poor connectivity. Devices are supposed to send "I'm alive" signals every hour. Without an automated system, engineers only discover a device is offline when someone manually checks the logs — far too late.

### The Solution

The Pulse-Check API implements a **Dead Man's Switch** pattern:

- A device **registers** a monitor with a timeout (e.g., 60 seconds).
- The system starts a countdown immediately.
- The device must **ping** the API before the timer runs out to reset the countdown.
- If the device goes silent and the timer hits zero, the system **fires an alert** and marks the device as `down`.
- A background scheduler continuously scans all monitors — no manual polling needed.

---

## 2. Architecture Diagram

### State Machine

Each monitor is a finite state machine with three states:

<img width="1536" height="1024" alt="state diagram" src="https://github.com/user-attachments/assets/d29879e5-30f8-4165-bee4-3b44f953a66e" />


---

### Sequence Diagram — Monitor Lifecycle

<img width="672" height="310" alt="Sequence monitor" src="https://github.com/user-attachments/assets/5122c431-1e92-4223-8ebe-5abf3cc9d4e4" />

### Sequence Diagram — Pause / Resume

<img width="672" height="135" alt="Sequence pause and resume" src="https://github.com/user-attachments/assets/c35292a3-c0a0-4c84-aa55-7d579f33cd86" />

---

### Project Structure

```
pulse-check-api/
│
├── src/
│   ├── main.py                      # Entry point (FastAPI app + scheduler wiring)
│   │
│   ├── controllers/                 # API layer — routes only, no business logic
│   │   ├── __init__.py
│   │   └── monitor_controller.py
│   │
│   ├── services/                    # Business logic (heartbeat, pause, alert)
│   │   ├── __init__.py
│   │   └── monitor_service.py
│   │
│   ├── store/                       # In-memory data layer
│   │   ├── __init__.py
│   │   └── monitor_store.py
│   │
│   ├── models/                      # Pydantic schemas + Monitor state machine
│   │   ├── __init__.py
│   │   └── monitor_model.py
│   │
│   ├── scheduler/                   # Background expiration checker
│   │   ├── __init__.py
│   │   └── monitor_scheduler.py
│   │
│   └── utils/                       # Shared helpers (time/UTC utilities)
│       ├── __init__.py
│       └── time_utils.py
│
├── images/
│   └── architecture-diagram.png    # Architecture diagram
│
├── tests/
│   ├── __init__.py
│   └── test_monitors.py            # 20 tests covering all requirements
│
├── README.md
├── requirements.txt
├── pytest.ini
├── .gitignore
└── LICENSE
```

---

## 3. Setup Instructions

### Prerequisites

- Python 3.10 or higher
- `pip`

---

### Step 1 — Clone the Repository

```bash
git clone https://github.com/CynthiaAdeline/AmaliTech-DEG-Project-based-challenges.git
cd AmaliTech-DEG-Project-based-challenges/backend/Pulse-Check
```

---

### Step 2 — Create and Activate a Virtual Environment

**macOS / Linux:**
```bash
python -m venv venv
source venv/bin/activate
```

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

---

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

---

### Step 4 — Run the Server

```bash
uvicorn src.main:app --reload
```

You should see output like this:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
⏱  Scheduler started (poll interval: 1s)
```

The API is now live at `http://localhost:8000`.

| URL | Description |
|-----|-------------|
| `http://localhost:8000` | Health check |
| `http://localhost:8000/docs` | Swagger UI (interactive) |
| `http://localhost:8000/redoc` | ReDoc documentation |

To stop the server press `CTRL+C`.

---

### Step 5 — Run Tests

```bash
python -m pytest tests/ -v
```

All 20 tests should pass.

---

## 4. API Documentation

### Base URL

```
https://amalitech-deg-project-based-challenges-c1mx.onrender.com
```

---

### `POST /monitors` — Register a Monitor

Creates a new monitor and starts the countdown immediately.

**Request Body**

```json
{
  "id": "device-123",
  "timeout": 60,
  "alert_email": "admin@critmon.com"
}
```

| Field         | Type    | Required | Description                           |
|---------------|---------|----------|---------------------------------------|
| `id`          | string  | ✅       | Unique device identifier              |
| `timeout`     | integer | ✅       | Countdown duration in seconds (> 0)   |
| `alert_email` | string  | ✅       | Email to notify when device goes down |

**Responses**

| Status | Meaning                                       |
|--------|-----------------------------------------------|
| `201`  | Monitor created, countdown started            |
| `409`  | A monitor with this ID already exists         |
| `422`  | Validation error (bad timeout / invalid email)|

**Example**

```bash
curl -X POST http://localhost:8000/monitors \
  -H "Content-Type: application/json" \
  -d '{"id": "device-123", "timeout": 60, "alert_email": "admin@critmon.com"}'
```

**Response `201 Created`**

```json
{
  "id": "device-123",
  "timeout": 60,
  "status": "active",
  "alert_email": "admin@critmon.com",
  "expires_at": "2025-01-01T12:01:00Z",
  "remaining_seconds": 59.8,
  "created_at": "2025-01-01T12:00:00Z",
  "alert_count": 0
}
```

---

### `POST /monitors/{id}/heartbeat` — Send a Heartbeat

Resets the countdown. Safe under rapid concurrent requests.

| Prior Status | Result                                      |
|--------------|---------------------------------------------|
| `active`     | Timer reset to full timeout                 |
| `paused`     | Auto-resumed + timer reset → active         |
| `down`       | Monitor revived + timer reset → active      |
| missing      | 404 Not Found                               |

**Example**

```bash
curl -X POST http://localhost:8000/monitors/device-123/heartbeat
```

**Response `200 OK`**

```json
{
  "message": "Timer reset for monitor 'device-123'."
}
```

---

### `POST /monitors/{id}/pause` — Pause a Monitor

Freezes the countdown. No alerts fire while paused.  
Sending a heartbeat after a pause automatically resumes monitoring.

| Prior Status | Result                                   |
|--------------|------------------------------------------|
| `active`     | Timer frozen → paused                    |
| `paused`     | No-op, returns 200 with info message     |
| `down`       | 409 Conflict — heartbeat to revive first |
| missing      | 404 Not Found                            |

**Example**

```bash
curl -X POST http://localhost:8000/monitors/device-123/pause
```

**Response `200 OK`**

```json
{
  "message": "Monitor 'device-123' paused. No alerts will fire until resumed."
}
```

---

### `GET /monitors/{id}` — Get Monitor Status *(Developer's Choice)*

Returns the full current state of a monitor, including remaining seconds.

**Example**

```bash
curl http://localhost:8000/monitors/device-123
```

**Response `200 OK`**

```json
{
  "id": "device-123",
  "timeout": 60,
  "status": "active",
  "alert_email": "admin@critmon.com",
  "expires_at": "2025-01-01T12:01:00Z",
  "remaining_seconds": 42.1,
  "created_at": "2025-01-01T12:00:00Z",
  "alert_count": 0
}
```

---

### `GET /monitors` — List All Monitors *(Developer's Choice)*

Returns a summary of every registered monitor.

**Example**

```bash
curl http://localhost:8000/monitors
```

**Response `200 OK`**

```json
[
  {
    "id": "device-123",
    "timeout": 60,
    "status": "active",
    "alert_email": "admin@critmon.com",
    "expires_at": "2025-01-01T12:01:00Z",
    "remaining_seconds": 42.1,
    "created_at": "2025-01-01T12:00:00Z",
    "alert_count": 0
  },
  {
    "id": "weather-station-7",
    "timeout": 3600,
    "status": "down",
    "alert_email": "ops@critmon.com",
    "expires_at": null,
    "remaining_seconds": null,
    "created_at": "2025-01-01T10:00:00Z",
    "alert_count": 1
  }
]
```

---

### `DELETE /monitors/{id}` — Delete a Monitor *(Developer's Choice)*

Permanently removes a monitor. Use this to decommission a device cleanly.

**Example**

```bash
curl -X DELETE http://localhost:8000/monitors/device-123
```

**Response `200 OK`**

```json
{
  "message": "Monitor 'device-123' has been deleted."
}
```

---

### Alert Output

When a monitor's timer expires, the system logs a structured alert to the console:

```json
{
  "ALERT": "Device device-123 is down!",
  "time": "2025-01-01T12:01:00.123456+00:00",
  "device_id": "device-123",
  "alert_email": "admin@critmon.com"
}
```

A simulated email notification is also logged. To integrate a real email or webhook, replace the body of `fire_alert()` in `src/services/monitor_service.py` — no other file needs to change.

---

## 5. Core Logic Explanation

### Timer Management

Each `Monitor` stores an `expires_at` UTC timestamp: `now + timeout`. The timer is not a sleeping coroutine — it is a simple timestamp comparison, which makes it cheap and easy to reason about.

### Expiration Detection (`src/scheduler/monitor_scheduler.py`)

A single background `MonitorScheduler` polls all monitors every second:

```
for each monitor:
    if status != ACTIVE → skip (fast path, no lock)
    acquire monitor._lock
        re-check status (heartbeat may have just fired)
        if now >= expires_at:
            mark_down()
            fire_alert()
```

The double-check inside the lock is the key correctness guarantee: even if a heartbeat arrives at the exact same millisecond as the expiry check, only one wins the lock and the state is always consistent.

### Alert Fires Exactly Once

`mark_down()` sets `status = DOWN`. The scheduler's fast path skips any non-ACTIVE monitor, so once a monitor is marked down the alert branch is never entered again. `alert_count` is incremented inside the lock, making it a reliable audit counter.

### Concurrency Handling

| Lock | Scope | Protects |
|------|-------|----------|
| `MonitorStore._registry_lock` | Registry dict | Create / delete / list |
| `Monitor._lock` | Per-monitor | State transitions (heartbeat, pause, expiry) |

50 simultaneous heartbeats for the same device are serialised through the per-monitor lock — no state corruption, no duplicate timer resets.

### Edge Cases

| Scenario | Behaviour |
|---|---|
| Duplicate registration | 409 Conflict |
| Heartbeat on DOWN monitor | Revives → ACTIVE, timer reset |
| Pause on DOWN monitor | 409 Conflict |
| Pause on non-existent monitor | 404 Not Found |
| Very small timeout (1 s) | Works; scheduler catches it on next tick (≤ 1 s delay) |
| System restart | In-memory store cleared; monitors must re-register |

---

## 6. Developer's Choice Feature

### What was added

Three additional endpoints beyond the core spec:

- `GET /monitors/{id}` — inspect a single monitor's live state
- `GET /monitors` — list all monitors
- `DELETE /monitors/{id}` — decommission a monitor

### Why

The core spec defines a fire-and-forget alert system, but operators need **observability**. Without a status endpoint there is no way to:

- Confirm a monitor was registered correctly.
- Check how much time is left before an alert fires.
- See which devices are currently down vs. active vs. paused.
- Clean up monitors for decommissioned devices (without this, the store grows forever).

The `remaining_seconds` field is particularly useful — it lets a device or dashboard know exactly how close to the edge it is, enabling smarter heartbeat scheduling.

### How it improves the system

- **Debuggability** — engineers can query state without reading logs.
- **Dashboard-ready** — `GET /monitors` returns everything needed for a live fleet overview.
- **Clean lifecycle** — `DELETE /monitors/{id}` prevents memory leaks in long-running deployments.
- **Revive workflow** — the status endpoint confirms a revived device is back to `active` after a heartbeat.

---

## 7. Key Design Decisions

### Timer Strategy: Background Polling Loop

**Chosen approach:** A single `asyncio` task polls all monitors every second.

| Concern | Polling loop | Per-monitor `asyncio.sleep()` |
|---|---|---|
| Memory at scale (10 000 devices) | 1 task | 10 000 tasks |
| Alert deduplication | Trivial (status check in loop) | Requires extra coordination |
| Grace-period / retry logic | One place | Scattered across tasks |
| Restart / cancel | Cancel one task | Cancel thousands |

**Trade-off:** ~1 second resolution. For minute-scale timeouts (hourly heartbeats) this is entirely acceptable. If sub-second precision were required, a priority queue (min-heap on `expires_at`) with `asyncio.sleep(next_expiry - now)` would be the next step.

### Layered Architecture

| Layer | File | Responsibility |
|---|---|---|
| Controller | `monitor_controller.py` | HTTP parsing, status codes, error mapping |
| Service | `monitor_service.py` | Business logic, alert firing |
| Store | `monitor_store.py` | Data access, concurrency-safe CRUD |
| Model | `monitor_model.py` | State machine, Pydantic schemas |
| Scheduler | `monitor_scheduler.py` | Background expiry detection |
| Utils | `time_utils.py` | Centralised clock operations |

This separation means each layer can be tested or swapped independently.

### In-Memory State

Monitors live in a Python dict. This is intentional for this project scope — zero infrastructure dependencies, fast reads and writes. The `MonitorStore` interface is designed to be swapped for a Redis or PostgreSQL backend without touching any other module.

### Duplicate ID Policy: Reject (409)

Overwriting silently would hide bugs (e.g., a device accidentally re-registering and resetting its own timer). Explicit rejection forces the caller to be intentional.

### Heartbeat Revives DOWN Monitors

If a device comes back online after a failure, it should be able to resume monitoring without an operator manually deleting and re-creating the monitor. Reviving on heartbeat is the most operationally useful choice.

