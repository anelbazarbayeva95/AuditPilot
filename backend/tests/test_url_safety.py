"""Unit tests for the SSRF guard in url_safety.py. DNS resolution is mocked —
no real network access required."""

from __future__ import annotations

import socket

import pytest

from url_safety import UnsafeURLError, ensure_public_url, resolve_public_ips


def _mock_getaddrinfo(monkeypatch, *ips: str) -> None:
    def fake_getaddrinfo(host, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


async def test_public_ip_allowed(monkeypatch):
    _mock_getaddrinfo(monkeypatch, "93.184.216.34")
    await ensure_public_url("https://example.com")  # does not raise


@pytest.mark.parametrize(
    "ip",
    [
        "10.0.0.5",  # RFC1918 private
        "192.168.1.1",  # RFC1918 private
        "127.0.0.1",  # loopback
        "169.254.169.254",  # link-local / cloud metadata
        "::1",  # IPv6 loopback
        "fd00::1",  # IPv6 unique local
    ],
)
async def test_non_public_ip_rejected(monkeypatch, ip):
    _mock_getaddrinfo(monkeypatch, ip)
    with pytest.raises(UnsafeURLError, match="non-public"):
        await ensure_public_url("https://internal.example")


async def test_any_resolved_ip_being_private_is_enough_to_reject(monkeypatch):
    # A hostname resolving to a mix of public and private IPs is still unsafe —
    # nothing guarantees Playwright's own connection picks the public one.
    _mock_getaddrinfo(monkeypatch, "93.184.216.34", "127.0.0.1")
    with pytest.raises(UnsafeURLError):
        await ensure_public_url("https://mixed.example")


async def test_non_http_scheme_rejected(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("DNS should not be resolved for a rejected scheme")

    monkeypatch.setattr(socket, "getaddrinfo", fail_if_called)
    with pytest.raises(UnsafeURLError, match="scheme"):
        await ensure_public_url("file:///etc/passwd")


async def test_missing_hostname_rejected():
    with pytest.raises(UnsafeURLError, match="hostname"):
        await ensure_public_url("http:///path")


async def test_dns_failure_fails_closed(monkeypatch):
    def fake_getaddrinfo(host, port):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError, match="Could not resolve"):
        await ensure_public_url("https://does-not-resolve.example")


async def test_resolve_public_ips_returns_addresses_in_resolver_order(monkeypatch):
    # The egress proxy dials the first address, so order must be preserved.
    _mock_getaddrinfo(monkeypatch, "93.184.216.34", "93.184.216.35", "93.184.216.34")
    assert await resolve_public_ips("example.com") == ["93.184.216.34", "93.184.216.35"]


async def test_resolve_public_ips_rejects_non_public(monkeypatch):
    _mock_getaddrinfo(monkeypatch, "10.0.0.5")
    with pytest.raises(UnsafeURLError, match="non-public"):
        await resolve_public_ips("internal.example")
