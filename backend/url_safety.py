"""SSRF guard for user-supplied audit URLs.

Every audit path (`/audit`, `/audit/full`, `/report`, `/report/jobs`) ends up
calling `scraper.scrape_website()`, which drives a server-side headless
browser to whatever URL the caller submits. Without a check, a caller could
point that browser at an internal service, a cloud metadata endpoint
(169.254.169.254), or localhost — classic SSRF. `ensure_public_url()` is
called as the first thing `scrape_website()` does, so it's a single choke
point that covers every entry path, including the screenshot/Lighthouse
agents that only run after a scrape has already succeeded.

The check here runs once, before navigation. It is not enough on its own: the
browser then follows redirects and loads iframes/subresources without asking
again (and Playwright's request routing never sees redirect hops). So every
audit browser is additionally pointed at `egress_proxy.EgressProxy`, which runs
`resolve_public_ips()` on every connection the browser opens and dials the
vetted IP itself — which also closes the DNS-rebinding window between this
check and the browser's own connection.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = {"http", "https"}


class UnsafeURLError(Exception):
    """Raised when a URL is rejected as unsafe to fetch server-side."""


async def ensure_public_url(url: str) -> None:
    """Raises UnsafeURLError unless `url` is http(s) and resolves only to public IPs.

    DNS resolution failure is treated as unsafe (fails closed) rather than
    silently letting the request through.
    """
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_SCHEMES:
        raise UnsafeURLError(f"URL scheme '{parts.scheme}' is not allowed")

    host = parts.hostname
    if not host:
        raise UnsafeURLError(f"URL '{url}' has no hostname")

    await resolve_public_ips(host)


async def resolve_public_ips(host: str) -> list[str]:
    """Resolves `host` and returns its addresses, or raises UnsafeURLError if any is non-public.

    Every address must be public, not just one: nothing guarantees which of
    them a client ends up connecting to.
    """
    try:
        # getaddrinfo is blocking, so run it off the event loop.
        infos = await asyncio.get_running_loop().run_in_executor(
            None, socket.getaddrinfo, host, None
        )
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}': {exc}") from exc

    # Ordered de-dupe: getaddrinfo's order is the system's preference order.
    resolved_ips = list(dict.fromkeys(info[4][0] for info in infos))
    if not resolved_ips:
        raise UnsafeURLError(f"Host '{host}' did not resolve to any address")

    for raw_ip in resolved_ips:
        # IPv6 scope ids (e.g. "%eth0") aren't valid input to ip_address().
        ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
        if not ip.is_global:
            raise UnsafeURLError(
                f"Host '{host}' resolves to non-public address {ip} — refusing to fetch"
            )
    return resolved_ips
