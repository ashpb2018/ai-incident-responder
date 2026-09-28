"""Webhook HMAC verification."""

from __future__ import annotations

import hashlib
import hmac

from incident_sentinel.ingest import verify_hmac


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_skips_when_no_secret():
    assert verify_hmac("", b"anything", None) is True


def test_valid_signature_accepted():
    body = b'{"event":"x"}'
    assert verify_hmac("s3cret", body, _sign("s3cret", body)) is True


def test_prefixed_signature_accepted():
    body = b"payload"
    assert verify_hmac("s3cret", body, f"v1={_sign('s3cret', body)}") is True


def test_wrong_signature_rejected():
    assert verify_hmac("s3cret", b"payload", "deadbeef") is False


def test_missing_signature_rejected_when_secret_set():
    assert verify_hmac("s3cret", b"payload", None) is False
