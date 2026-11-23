"""Timestamped HMAC webhooks with public-target validation and bounded retries."""
from __future__ import annotations

import hashlib
import hmac
import json
import random
import time
import uuid

import httpx

from ..network_safety import validate_public_target_url


def sign_delivery(body: bytes, secret: str, *, timestamp: int | None = None,
                  delivery_id: str | None = None) -> dict[str, str]:
    if not secret:
        raise ValueError("webhook signing secret is required")
    ts = str(int(time.time()) if timestamp is None else timestamp)
    identifier = delivery_id or uuid.uuid4().hex
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"X-Finesse-Timestamp": ts, "X-Finesse-Signature": f"v1={digest}",
            "X-Finesse-Delivery-Id": identifier}


def verify_delivery(body: bytes, secret: str, timestamp: str, signature: str,
                    *, now: float | None = None, tolerance_s: int = 300) -> bool:
    try:
        age = abs((time.time() if now is None else now) - int(timestamp))
    except (TypeError, ValueError):
        return False
    expected = sign_delivery(body, secret, timestamp=int(timestamp), delivery_id="verify")[
        "X-Finesse-Signature"]
    return age <= tolerance_s and hmac.compare_digest(expected, signature)


async def dispatch(url: str, event: dict, secret: str, *, client=None,
                   retries: int = 5) -> dict:
    if retries < 0 or retries > 5:
        raise ValueError("retries must be between 0 and 5")
    validate_public_target_url(url)
    body = json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", **sign_delivery(body, secret)}
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=10.0, follow_redirects=False)
    try:
        for attempt in range(retries + 1):
            try:
                response = await http.post(url, content=body, headers=headers)
                if response.status_code < 500 and response.status_code != 429:
                    return {"delivery_id": headers["X-Finesse-Delivery-Id"],
                            "status_code": response.status_code, "attempt": attempt + 1,
                            "delivered": response.is_success}
                last_error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            if attempt < retries:
                import asyncio
                await asyncio.sleep(min(30.0, (2 ** attempt) + random.random()))
        return {"delivery_id": headers["X-Finesse-Delivery-Id"], "delivered": False,
                "attempt": retries + 1, "error": last_error}
    finally:
        if owns_client:
            await http.aclose()
