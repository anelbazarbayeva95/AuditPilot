"""SSRF guard for user-supplied audit URLs.

Every audit path (`/audit`, `/audit/full`, `/report`, `/report/jobs`) ends up
calling `scraper.scrape_website()`, which drives a server-side headless
browser to whatever URL the caller submits. Without a check, a caller could
point that browser at an internal service, a cloud metadata endpoint
(169.254.169.254), or localhost — classic SSRF. `ensure_public_url()` is
called as the first thing `scrape_website()` does, so it's a single choke
point that covers every entry path, including the screenshot/Lighthouse
agents that only run after a scrape has already succeeded.

Known limitation: this checks DNS resolution at call time, not at the
moment Playwright actually connects, so a hostname that resolves publicly
now but is rebound to a private IP by the time the browser navigates (DNS
rebinding) would slip through. Closing that gap fully would require pinning
the resolved IP into the browser's own connection, which Playwright doesn't
expose cleanly — out of scope here. This still stops the overwhelming
majority of real-world attempts (raw private/loopback/metadata IPs and
hostnames that plainly resolve to them).
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

    try:
        # getaddrinfo is blocking, so run it off the event loop.
        infos = await asyncio.get_running_loop().run_in_executor(
            None, socket.getaddrinfo, host, None
        )
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{host}': {exc}") from exc

    resolved_ips = {info[4][0] for info in infos}
    if not resolved_ips:
        raise UnsafeURLError(f"Host '{host}' did not resolve to any address")

    for raw_ip in resolved_ips:
        # IPv6 scope ids (e.g. "%eth0") aren't valid input to ip_address().
        ip = ipaddress.ip_address(raw_ip.split("%", 1)[0])
        if not ip.is_global:
            raise UnsafeURLError(
                f"Host '{host}' resolves to non-public address {ip} — refusing to fetch"
            )
