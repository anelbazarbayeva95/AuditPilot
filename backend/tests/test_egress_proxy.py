"""Tests for the egress guard proxy (egress_proxy.py).

Everything runs against loopback servers with an injected resolver — no real
DNS or network. "public.test" stands in for a public host (it resolves to a
local upstream server); every other host is refused, the way a private /
loopback / metadata address would be by url_safety.resolve_public_ips().
"""

from __future__ import annotations

import asyncio

import pytest

from egress_proxy import EgressProxy, _split_host_port
from url_safety import UnsafeURLError


@pytest.fixture
async def upstream():
    """A loopback server that records what it receives and answers one HTTP response."""
    received: list[bytes] = []

    async def handle(reader, writer):
        data = await reader.read(65536)
        received.append(data)
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\n\r\nhello")
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield port, received
    server.close()
    await server.wait_closed()


def _resolver():
    async def resolve(host: str) -> list[str]:
        if host == "public.test":
            return ["127.0.0.1"]
        raise UnsafeURLError(f"Host '{host}' resolves to non-public address")

    return resolve


async def _exchange(proxy: EgressProxy, request: bytes) -> bytes:
    port = int(proxy.server.rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    response = await asyncio.wait_for(reader.read(65536), timeout=5)
    writer.close()
    return response


async def test_plain_http_to_public_host_is_forwarded_in_origin_form(upstream):
    port, received = upstream
    async with EgressProxy(resolve=_resolver()) as proxy:
        response = await _exchange(
            proxy,
            f"GET http://public.test:{port}/path?q=1 HTTP/1.1\r\nHost: public.test:{port}\r\n"
            "Proxy-Connection: keep-alive\r\n\r\n".encode(),
        )
    assert response.startswith(b"HTTP/1.1 200")
    assert response.endswith(b"hello")
    sent = received[0]
    assert sent.startswith(b"GET /path?q=1 HTTP/1.1\r\n")
    # Proxy-addressed headers are stripped; the origin is asked to close so
    # each request gets its own freshly checked connection.
    assert b"Proxy-Connection" not in sent
    assert b"Connection: close" in sent


async def test_plain_http_to_non_public_host_is_refused(upstream):
    port, received = upstream
    async with EgressProxy(resolve=_resolver()) as proxy:
        response = await _exchange(
            proxy, f"GET http://169.254.169.254:{port}/latest/meta-data HTTP/1.1\r\n\r\n".encode()
        )
        assert proxy.blocked == ["169.254.169.254"]
        assert proxy.refusal("https://example.com") == (
            "Refused to load 'https://example.com': it led to a non-public address (169.254.169.254)"
        )
    assert response.startswith(b"HTTP/1.1 403")
    assert received == []


async def test_connect_to_public_host_opens_a_tunnel(upstream):
    port, received = upstream
    async with EgressProxy(resolve=_resolver()) as proxy:
        proxy_port = int(proxy.server.rsplit(":", 1)[1])
        reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
        writer.write(f"CONNECT public.test:{port} HTTP/1.1\r\nHost: public.test:{port}\r\n\r\n".encode())
        await writer.drain()
        established = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=5)
        assert established.startswith(b"HTTP/1.1 200")

        # Bytes now pass through untouched (in reality, the browser's TLS).
        writer.write(b"opaque-bytes")
        await writer.drain()
        tunneled = await asyncio.wait_for(reader.read(65536), timeout=5)
        writer.close()
    assert received == [b"opaque-bytes"]
    assert tunneled.endswith(b"hello")


async def test_connect_to_non_public_host_is_refused(upstream):
    port, received = upstream
    async with EgressProxy(resolve=_resolver()) as proxy:
        response = await _exchange(proxy, f"CONNECT internal.test:{port} HTTP/1.1\r\n\r\n".encode())
        assert proxy.blocked == ["internal.test"]
    assert response.startswith(b"HTTP/1.1 403")
    assert received == []


async def test_unreachable_upstream_is_a_bad_gateway():
    async with EgressProxy(resolve=_resolver()) as proxy:
        # Port 9 (discard) has nothing listening on loopback here.
        response = await _exchange(proxy, b"CONNECT public.test:9 HTTP/1.1\r\n\r\n")
        assert proxy.blocked == []
    assert response.startswith(b"HTTP/1.1 502")


async def test_non_http_absolute_form_is_rejected():
    async with EgressProxy(resolve=_resolver()) as proxy:
        response = await _exchange(proxy, b"GET ftp://public.test/file HTTP/1.1\r\n\r\n")
    assert response.startswith(b"HTTP/1.1 400")


async def test_refusal_is_none_when_nothing_was_blocked():
    async with EgressProxy(resolve=_resolver()) as proxy:
        assert proxy.refusal("https://example.com") is None


async def test_server_url_unavailable_outside_context():
    with pytest.raises(RuntimeError):
        _ = EgressProxy().server


@pytest.mark.parametrize(
    "target, expected",
    [
        ("example.com:443", ("example.com", 443)),
        ("example.com", ("example.com", 443)),
        ("[::1]:8443", ("::1", 8443)),
        ("example.com:notaport", ("", 443)),
    ],
)
def test_split_host_port(target, expected):
    assert _split_host_port(target, default_port=443) == expected
