"""
Simulated payment processor.

In a real system this would call an external payment gateway (Stripe, Paystack, etc.).
Here we simply wait 2 seconds to mimic network/processing latency and return a
confirmation message.
"""

import asyncio


async def process_payment(amount: float, currency: str) -> dict:
    """
    Simulate a payment charge with a 2-second processing delay.

    Returns:
        dict: A response payload confirming the charge.
    """
    await asyncio.sleep(2)
    return {
        "message": f"Charged {amount} {currency}",
        "amount": amount,
        "currency": currency,
    }
