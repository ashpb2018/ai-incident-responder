"""SSRF protection shared by the network-facing diagnostic tools.

The agent's URL/hostname arguments come from an LLM, which an attacker may be
able to influence via a crafted alert. To stop the agent from being turned into
a server-side request forgery primitive, we refuse to touch anything that
resolves to a private, loopback, link-local, or otherwise non-public address —
which is what protects cloud metadata endpoints such as 169.254.169.254.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

_ALLOWED_SCHEMES = {"http", "https"}


class BlockedTarget(ValueError):
    """Raised when a requested host/URL is not allowed."""


def _addresses_for(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise BlockedTarget(f"could not resolve host {host!r}: {exc}") from exc
    return sorted({info[4][0] for info in infos})


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_public_host(host: str) -> None:
    """Raise :class:`BlockedTarget` unless every resolved address is public."""
    if not host:
        raise BlockedTarget("empty host")
    # A bare IP literal is checked directly; a name is resolved first.
    try:
        candidates = [str(ipaddress.ip_address(host))]
    except ValueError:
        candidates = _addresses_for(host)
    for address in candidates:
        if not _is_public(address):
            raise BlockedTarget(
                f"host {host!r} resolves to non-public address {address}; refused"
            )


def assert_public_url(url: str) -> str:
    """Validate a URL's scheme and host, returning the parsed hostname."""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BlockedTarget(f"scheme {parsed.scheme!r} not allowed (use http/https)")
    if not parsed.hostname:
        raise BlockedTarget("URL has no host")
    assert_public_host(parsed.hostname)
    return parsed.hostname
