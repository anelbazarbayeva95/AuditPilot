"""Egress guard: a loopback forward proxy that every audit browser is pointed at.

`url_safety.ensure_public_url()` vets the submitted URL once, before
navigation. The browser then follows HTTP redirects and loads iframes and
subresources without asking again — and Playwright's request routing does not
see redirect hops at all (verified: a public URL answering
`302 → http://<private host>/` was followed and rendered with routing active).
So a public URL redirecting to 169.254.169.254, or a page iframing an internal
host, would land internal content in the scrape or the screenshot.

Routing every browser connection through this proxy closes that: each CONNECT
tunnel and each plain-HTTP request is resolved and checked here, at connect
time, and the proxy dials the vetted IP itself. Because the browser never does
its own DNS lookup, a hostname re-pointed between the check and the connection
(DNS rebinding) can't slip through either.

Usage — one proxy per browser session, bound to 127.0.0.1 on a free port:

    async with EgressProxy() as proxy:
        browser = await pw.chromium.launch(proxy={"server": proxy.server})

`proxy.blocked` lists every host refused during the session, so a failed
navigation can be reported as "redirected to a non-public address" instead of
Chrome's opaque ERR_TUNNEL_CONNECTION_FAILED.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from url_safety import UnsafeURLError, resolve_public_ips

logger = logging.getLogger(__name__)

Resolver = Callable[[str], Awaitable[list[str]]]

UPSTREAM_CONNECT_TIMEOUT_S = 10
_CHUNK = 64 * 1024

# Hop-by-hop headers the browser addresses to the proxy, not the origin.
_HOP_BY_HOP = {b"connection", b"keep-alive", b"proxy-connection", b"proxy-authorization", b"te", b"upgrade"}


class EgressProxy:
    """Async context manager running the guard proxy for one browser session."""

    def __init__(self, resolve: Resolver = resolve_public_ips) -> None:
        # Injectable so tests can stand in for DNS without touching the network.
        self._resolve = resolve
        self._server: asyncio.base_events.Server | None = None
        self._writers: set[asyncio.StreamWriter] = set()
        self.blocked: list[str] = []

    @property
    def server(self) -> str:
        """The proxy URL to hand to Playwright / Chrome's --proxy-server."""
        if self._server is None:
            raise RuntimeError("EgressProxy is not running")
        port = self._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def refusal(self, url: str) -> str | None:
        """A readable reason for a failed navigation, if this proxy refused a host during it."""
        if not self.blocked:
            return None
        return f"Refused to load '{url}': it led to a non-public address ({self.blocked[-1]})"

    async def __aenter__(self) -> "EgressProxy":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._server is None:
            return
        self._server.close()
        for writer in list(self._writers):
            writer.close()
        # Bounded: on Python 3.12+ wait_closed() also waits for every handler,
        # and a browser that was killed mid-transfer shouldn't hang shutdown.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._server.wait_closed(), timeout=5)
        self._server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)
        upstream: asyncio.StreamWriter | None = None
        try:
            try:
                head = await reader.readuntil(b"\r\n\r\n")
            except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
                return

            request_line, _, header_block = head.partition(b"\r\n")
            try:
                method, target, version = request_line.decode("latin-1").split(" ", 2)
            except ValueError:
                await _reply(writer, 400, "Bad Request")
                return

            if method == "CONNECT":
                host, port = _split_host_port(target, default_port=443)
                parts = None
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    await _reply(writer, 400, "Bad Request")
                    return
                host, port = parts.hostname, parts.port or 80

            if not host:
                await _reply(writer, 400, "Bad Request")
                return

            try:
                addresses = await self._resolve(host)
            except UnsafeURLError as exc:
                self.blocked.append(host)
                logger.warning("egress.blocked host=%s reason=%s", host, exc)
                await _reply(writer, 403, "Forbidden")
                return

            try:
                upstream_reader, upstream = await asyncio.wait_for(
                    asyncio.open_connection(addresses[0], port), timeout=UPSTREAM_CONNECT_TIMEOUT_S
                )
            except (OSError, asyncio.TimeoutError) as exc:
                logger.info("egress.upstream_unreachable host=%s port=%s error=%s", host, port, exc)
                await _reply(writer, 502, "Bad Gateway")
                return
            self._writers.add(upstream)

            if method == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await writer.drain()
                await _tunnel(reader, writer, upstream_reader, upstream)
            else:
                await self._forward_plain_http(
                    method, parts, version, header_block, reader, writer, upstream_reader, upstream
                )
        except Exception as exc:  # noqa: BLE001 - one bad connection must never take the proxy down
            logger.debug("egress.connection_error error=%s", exc)
        finally:
            for w in (writer, upstream):
                if w is not None:
                    self._writers.discard(w)
                    w.close()

    async def _forward_plain_http(
        self, method, parts, version, header_block, reader, writer, upstream_reader, upstream
    ) -> None:
        """Forwards exactly one plain-HTTP request, then closes.

        Browsers reuse a proxy connection for requests to *different* hosts,
        so piping the client connection through would send a later request to
        this already-vetted upstream regardless of its own host. One request
        per connection, with `Connection: close` both ways, keeps every
        request on a freshly checked connection.
        """
        headers = []
        content_length = 0
        for line in header_block.split(b"\r\n"):
            if not line:
                continue
            name = line.split(b":", 1)[0].strip().lower()
            if name in _HOP_BY_HOP:
                continue
            if name == b"transfer-encoding":
                # Chunked request bodies from a page are vanishingly rare;
                # refusing them is simpler than re-framing them.
                await _reply(writer, 501, "Not Implemented")
                return
            if name == b"content-length":
                content_length = int(line.split(b":", 1)[1].strip() or 0)
            headers.append(line)

        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        upstream.write(f"{method} {path} {version}\r\n".encode("latin-1"))
        upstream.write(b"\r\n".join(headers) + b"\r\nConnection: close\r\n\r\n")
        if content_length:
            upstream.write(await reader.readexactly(content_length))
        await upstream.drain()

        # The origin closes after one response (we asked it to), so its EOF
        # marks the end; closing our side then tells the browser not to reuse.
        await _pump(upstream_reader, writer)


def _split_host_port(target: str, default_port: int) -> tuple[str, int]:
    """'example.com:443' / '[::1]:443' → (host, port)."""
    if target.startswith("["):
        host, _, rest = target[1:].partition("]")
        port = rest.lstrip(":")
    else:
        host, _, port = target.rpartition(":") if ":" in target else (target, "", "")
    try:
        return host, int(port) if port else default_port
    except ValueError:
        return "", default_port


async def _pump(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(_CHUNK):
            dst.write(data)
            await dst.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


async def _tunnel(client_r, client_w, upstream_r, upstream_w) -> None:
    """Pipes both directions until either side closes."""
    tasks = [
        asyncio.ensure_future(_pump(client_r, upstream_w)),
        asyncio.ensure_future(_pump(upstream_r, client_w)),
    ]
    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


async def _reply(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
    with contextlib.suppress(ConnectionError):
        writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
