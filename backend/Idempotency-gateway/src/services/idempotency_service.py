"""
Idempotency Service — core business logic.

Responsibilities:
  - Check whether an idempotency key has been seen before.
  - Detect body conflicts (same key, different payload).
  - Handle in-flight requests by waiting on a shared asyncio.Event.
  - Delegate to the payment processor for new requests.
  - Persist results so duplicate requests get the exact same response.
"""

import asyncio
from typing import Any, Dict, Tuple

from src.services.payment_processor import process_payment
from src.store.idempotency_store import (
    body_matches,
    complete_record,
    create_record,
    get_record,
)

# HTTP status code used for new successful payments.
PAYMENT_STATUS_CODE = 201


async def handle_payment_request(
    idempotency_key: str,
    request_body: Dict[str, Any],
) -> Tuple[Dict[str, Any], int, Dict[str, str]]:
    """
    Process a payment request with full idempotency guarantees.

    Returns:
        (response_body, status_code, extra_headers)

    Raises:
        ConflictError: when the key exists but the body differs.
    """
    record = get_record(idempotency_key)

    # ------------------------------------------------------------------ #
    # CASE 1 — Key not found (or expired): first-time request             #
    # ------------------------------------------------------------------ #
    if record is None:
        # Reserve the key immediately to block concurrent duplicates.
        record = create_record(idempotency_key, request_body)

        try:
            amount = request_body["amount"]
            currency = request_body["currency"]
            response_body = await process_payment(amount, currency)
            status_code = PAYMENT_STATUS_CODE
            response_headers: Dict[str, str] = {}
        except Exception:
            # On processor failure remove the reservation so the client
            # can retry with the same key.
            from src.store.idempotency_store import store
            store.pop(idempotency_key, None)
            raise

        complete_record(idempotency_key, response_body, status_code, response_headers)
        return response_body, status_code, response_headers

    # ------------------------------------------------------------------ #
    # CASE 2 — Key exists but request is still in-flight                  #
    # ------------------------------------------------------------------ #
    if record["status"] == "processing":
        # Keep a reference to the original record object BEFORE waiting.
        # If the record is evicted by TTL during the wait, we can still
        # read the completed data from this local reference.
        inflight_record = record

        # Wait until the first request finishes (event.set() is called in
        # complete_record).  This prevents race conditions: no second charge
        # is ever triggered, and the caller gets the real result.
        await inflight_record["event"].wait()

        # Prefer the freshly-fetched record; fall back to the local reference
        # if TTL eviction removed it from the store during the wait window.
        record = get_record(idempotency_key) or inflight_record

    # ------------------------------------------------------------------ #
    # CASE 3 — Key exists and is completed: check for conflict            #
    # ------------------------------------------------------------------ #
    if not body_matches(record, request_body):
        raise ConflictError(
            "Idempotency key already used for a different request body."
        )

    # ------------------------------------------------------------------ #
    # CASE 4 — Exact duplicate: replay stored response                    #
    # ------------------------------------------------------------------ #
    extra_headers = {"X-Cache-Hit": "true"}
    return record["response_body"], record["status_code"], extra_headers


# --------------------------------------------------------------------------- #
# Custom exceptions                                                             #
# --------------------------------------------------------------------------- #

class ConflictError(Exception):
    """Raised when the same idempotency key is reused with a different body."""
