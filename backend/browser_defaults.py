"""
Shared Playwright browser-context defaults for scraper.py and screenshot.py.

Both hit the same real websites for the same audit, so they should present an
identical, realistic browser fingerprint. Left at Playwright's defaults, a
headless Chromium page identifies itself with a "HeadlessChrome" user-agent
string and other headless-only signals — a number of real sites block that
outright (this project has hit dyson.com returning HTTP 403 specifically
because of this).

Setting a realistic desktop Chrome user-agent/locale/viewport isn't spoofing
in a deceptive sense here: an audit tool exists specifically to see the page
the way a real visitor's browser renders it, which is exactly what
Lighthouse-style auditing tools do too. It also isn't a guaranteed fix —
sites with more sophisticated bot protection (TLS fingerprinting, JS
challenges, IP reputation) may still block a headless browser regardless of
the user-agent string.
"""

from __future__ import annotations

DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DESKTOP_LOCALE = "en-US"
DESKTOP_VIEWPORT = {"width": 1280, "height": 900}
