"""kubectl argument validation must block flag injection."""

from __future__ import annotations

import pytest

from incident_sentinel.tools.kubernetes import InvalidArgument, _safe


def test_rejects_leading_dash():
    with pytest.raises(InvalidArgument):
        _safe("--kubeconfig=/etc/evil", field="namespace")
    with pytest.raises(InvalidArgument):
        _safe("--as=system:admin", field="name")


def test_rejects_empty():
    with pytest.raises(InvalidArgument):
        _safe("   ", field="pod")


def test_rejects_shell_ish_characters():
    with pytest.raises(InvalidArgument):
        _safe("name;rm -rf", field="name")


def test_allows_normal_names():
    assert _safe("checkout-7d9f", field="pod") == "checkout-7d9f"
    assert _safe("kube-system", field="namespace") == "kube-system"
