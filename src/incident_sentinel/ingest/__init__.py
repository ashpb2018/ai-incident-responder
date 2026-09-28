"""Turn vendor webhook payloads into normalised :class:`Alert` objects."""

from __future__ import annotations

from .opsgenie import parse_opsgenie
from .pagerduty import parse_pagerduty
from .signature import verify_hmac

__all__ = ["parse_opsgenie", "parse_pagerduty", "verify_hmac"]
