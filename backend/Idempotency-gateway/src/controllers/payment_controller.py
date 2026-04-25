"""
Payment controller — FastAPI route handler for POST /process-payment.

Handles:
  - Header validation (Idempotency-Key required)
  - Body validation (amount: number, currency: string)
  - Delegation to the idempotency service
  - Mapping service results / exceptions to HTTP responses
"""

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from typing import Optional

from src.services.idempotency_service import ConflictError, handle_payment_request

router = APIRouter()


# --------------------------------------------------------------------------- #
# Request schema                                                                #
# --------------------------------------------------------------------------- #

class PaymentRequest(BaseModel):
    amount: float
    currency: str

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("amount must be a positive number")
        return v

    @field_validator("currency")
    @classmethod
    def currency_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("currency must be a non-empty string")
        return v.strip().upper()


# --------------------------------------------------------------------------- #
# Route                                                                         #
# --------------------------------------------------------------------------- #

@router.post("/process-payment", status_code=201)
async def process_payment_endpoint(
    body: PaymentRequest,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """
    Process a payment exactly once per unique Idempotency-Key.

    Headers:
        Idempotency-Key (required): A unique string identifying this request.

    Body:
        amount   (number)  — charge amount
        currency (string)  — ISO currency code, e.g. "GHS", "USD"

    Returns:
        201 Created on first successful charge.
        Replays stored response on duplicate requests (X-Cache-Hit: true).
        409 Conflict when the key is reused with a different body.
    """
    # Validate presence of Idempotency-Key header.
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required",
        )

    request_body = body.model_dump()

    try:
        response_body, status_code, extra_headers = await handle_payment_request(
            idempotency_key.strip(), request_body
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    response = JSONResponse(content=response_body, status_code=status_code)
    for header_name, header_value in extra_headers.items():
        response.headers[header_name] = header_value

    return response
