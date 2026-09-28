"""Webhook signature verification.

Both PagerDuty and OpsGenie sign webhook bodies with an HMAC-SHA256 of the raw
request body using a shared secret. :func:`verify_hmac` compares that in
constant time. When no secret is configured, verification is skipped (returns
``True``) so local development does not require one.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac(secret: str, body: bytes, provided: str | None) -> bool:
    """Return ``True`` if ``provided`` is a valid HMAC-SHA256 of ``body``.

    A signature may arrive as a bare hex digest or prefixed (e.g. ``v1=<hex>``);
    the last ``=``-delimited field is used. Verification is skipped when no
    secret is set.
    """
    if not secret:
        return True
    if not provided:
        return False

    candidate = provided.split("=")[-1].strip()
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, candidate)
