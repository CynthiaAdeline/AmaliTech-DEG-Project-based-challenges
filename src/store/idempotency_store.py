"""
In-memory store for idempotency records.

Each record is keyed by the Idempotency-Key header value and holds
all data needed to replay or detect duplicate/conflict requests.
"""

import asyncio
import hashlib
import json
import time
from typing import Any, Dict, Optional

# The single in-memory store — plain Python dict, no external dependencies.
store: Dict[str, Dict[str, Any]] = {}

# TTL in seconds: records older than this are treated as expired / non-existent.
# 10 minutes is the standard window used by payment APIs (e.g. Stripe uses 24h
# in production; 600s is a sensible default for a demo/fintech assessment).
TTL_SECONDS: int = 600  # 10 minutes


def _hash_body(body: Dict[str, Any]) -> str:
    """Return a stable SHA-256 hex digest of a request body dict."""
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def is_expired(record: Dict[str, Any]) -> bool:
    """Return True if the record has exceeded the TTL."""
    return (time.time() - record["created_at"]) > TTL_SECONDS


def get_record(key: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a record by idempotency key.
    Returns None if the key does not exist or the record has expired.
    Expired records are lazily evicted on access.
    """
    record = store.get(key)
    if record is None:
        return None
    if is_expired(record):
        del store[key]
        return None
    return record


def create_record(key: str, request_body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insert a new record in 'processing' state.
    An asyncio.Event is attached so concurrent requests can wait on it.
    """
    record: Dict[str, Any] = {
        "request_body": request_body,
        "request_hash": _hash_body(request_body),
        "response_body": None,
        "status_code": None,
        "response_headers": {},
        "status": "processing",
        "created_at": time.time(),
        "event": asyncio.Event(),
    }
    store[key] = record
    return record


def complete_record(
    key: str,
    response_body: Dict[str, Any],
    status_code: int,
    response_headers: Dict[str, str],
) -> None:
    """
    Transition a record from 'processing' to 'completed', persist the
    response, and signal any waiters via the asyncio.Event.
    """
    record = store.get(key)
    if record is None:
        # Guard: record was evicted between creation and completion (extremely
        # unlikely but defensive).  Nothing to update; waiters will fall back
        # to the local reference they held before calling event.wait().
        return
    record["response_body"] = response_body
    record["status_code"] = status_code
    record["response_headers"] = response_headers
    record["status"] = "completed"
    # Unblock all coroutines waiting on this key.
    record["event"].set()


def body_matches(record: Dict[str, Any], incoming_body: Dict[str, Any]) -> bool:
    """Return True if the incoming body hash matches the stored hash."""
    return record["request_hash"] == _hash_body(incoming_body)
