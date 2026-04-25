"""
Idempotency Gateway — application entry point.

Wires together:
  - FastAPI application
  - Logging middleware
  - Payment controller router
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.controllers.payment_controller import router as payment_router
from src.middleware.logging_middleware import LoggingMiddleware

app = FastAPI(
    title="Idempotency Gateway",
    description=(
        "A Pay-Once Protocol API that guarantees payments are processed "
        "exactly once, regardless of retries or network failures."
    ),
    version="1.0.0",
)

# ── Middleware ────────────────────────────────────────────────────────────── #
app.add_middleware(LoggingMiddleware)

# ── Routers ──────────────────────────────────────────────────────────────── #
app.include_router(payment_router)


# ── Health check ─────────────────────────────────────────────────────────── #
@app.get("/health", tags=["Health"])
async def health_check():
    """Simple liveness probe."""
    return JSONResponse(content={"status": "ok"})
