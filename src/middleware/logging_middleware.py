"""
Request/response logging middleware.

Logs each incoming request and its outcome (status code + latency).
Keeps operational visibility without coupling logging to business logic.
"""

import logging
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("idempotency_gateway")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        idempotency_key = request.headers.get("Idempotency-Key", "-")

        logger.info(
            "→ %s %s | Idempotency-Key: %s",
            request.method,
            request.url.path,
            idempotency_key,
        )

        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        logger.info(
            "← %s %s | status=%d | %.1f ms | Idempotency-Key: %s",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            idempotency_key,
        )
        return response
