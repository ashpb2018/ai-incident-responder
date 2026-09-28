"""SSRF guard: private/loopback/link-local targets must be refused."""

from __future__ import annotations

import pytest

from incident_sentinel.tools.netguard import (
    BlockedTarget,
    assert_public_host,
    assert_public_url,
)


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "0.0.0.0",
        "10.0.0.5",
        "192.168.1.1",
        "172.16.0.1",
        "169.254.169.254",  # cloud metadata endpoint
        "::1",
    ],
)
def test_private_and_metadata_hosts_are_blocked(host):
    with pytest.raises(BlockedTarget):
        assert_public_host(host)


def test_public_ip_is_allowed():
    assert_public_host("8.8.8.8")  # should not raise


def test_non_http_scheme_blocked():
    with pytest.raises(BlockedTarget):
        assert_public_url("file:///etc/passwd")
    with pytest.raises(BlockedTarget):
        assert_public_url("gopher://example.com")


def test_metadata_url_blocked():
    with pytest.raises(BlockedTarget):
        assert_public_url("http://169.254.169.254/latest/meta-data/")


def test_public_url_returns_host():
    assert assert_public_url("https://8.8.8.8/health") == "8.8.8.8"
