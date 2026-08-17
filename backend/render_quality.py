"""
Measures whether a captured screenshot is usable as visual evidence.

A headless capture can succeed at every level the browser reports — HTTP 200,
`load` fired, PNG bytes returned — and still be a picture of nothing: hero
media that lazy-loads on scroll and never fired, webfonts that never resolved,
a layout waiting on a fetch that finished after the shutter. Nothing in the
Playwright API distinguishes that from a good render, so it has to be measured
from the pixels.

This matters beyond tidiness. An audit that evaluates a blank capture as if it
were the real page produces confident claims about elements that aren't in its
own screenshot, and one visible contradiction like that costs the reader's
trust in every other finding. So the pipeline measures the render and declines
to judge what it couldn't see.

Thresholds are calibrated against a real failure: a nike.com capture that came
back 71% one flat color, with 64% of its rows a single color and no content at
all above y=740 of 900.
"""

from __future__ import annotations

import io
import logging
from collections import Counter
from typing import Optional

from models.schemas import ScreenshotQuality

logger = logging.getLogger(__name__)

# A real page still has large flat regions (backgrounds, whitespace), so these
# have to sit well above "clean design" and only trigger on genuine emptiness.
DOMINANT_COLOR_PCT_LIMIT = 60.0   # measured failure: 71.3%
UNIFORM_ROW_PCT_LIMIT = 60.0      # measured failure: 64.3%
CONTENT_TOP_PCT_LIMIT = 50.0      # measured failure: first content at 82% down

# A row counts as "uniform" when nearly every pixel in it is the same color.
_UNIFORM_ROW_THRESHOLD = 0.99

# Analysis runs on a downscaled copy — 1280x900 is 1.15M pixels and the
# statistics are scale-invariant, so this keeps a per-audit check to a few
# milliseconds without changing the verdict.
_ANALYSIS_WIDTH = 240


def analyze_render_quality(png_bytes: bytes) -> ScreenshotQuality:
    """Judge whether `png_bytes` shows a real render or an empty one.

    Never raises: an image that can't be decoded (or a Pillow that isn't
    installed) yields status "unknown", which the report discloses as
    unverified rather than treating as either pass or fail.
    """
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover - Pillow ships with reportlab
        logger.warning("render_quality.unavailable reason=pillow_missing")
        return ScreenshotQuality(status="unknown", reason="Render quality could not be measured.")

    try:
        with Image.open(io.BytesIO(png_bytes)) as img:
            image = img.convert("RGB")
            width, height = image.size
            if width == 0 or height == 0:
                return ScreenshotQuality(status="unknown", reason="Screenshot has no pixels.")
            if width > _ANALYSIS_WIDTH:
                scale = _ANALYSIS_WIDTH / width
                image = image.resize((_ANALYSIS_WIDTH, max(1, int(height * scale))))
            width, height = image.size
            # tobytes() rather than getdata(): getdata() is deprecated in
            # Pillow 14 and its replacement doesn't exist in older versions,
            # and Pillow's version is whatever reportlab pulled in.
            raw = image.tobytes()
            pixels = [raw[i:i + 3] for i in range(0, len(raw), 3)]
    except Exception as exc:  # noqa: BLE001 - a bad image must not break an audit
        logger.warning("render_quality.undecodable error=%s", exc)
        return ScreenshotQuality(status="unknown", reason="Screenshot could not be decoded.")

    total = len(pixels)
    dominant_count = Counter(pixels).most_common(1)[0][1]
    dominant_pct = dominant_count / total * 100

    uniform_rows = 0
    first_content_row: Optional[int] = None
    for y in range(height):
        row = pixels[y * width:(y + 1) * width]
        row_dominant = Counter(row).most_common(1)[0][1]
        if row_dominant / width >= _UNIFORM_ROW_THRESHOLD:
            uniform_rows += 1
        elif first_content_row is None:
            first_content_row = y

    uniform_row_pct = uniform_rows / height * 100
    content_top_pct = 100.0 if first_content_row is None else first_content_row / height * 100

    reasons = []
    if dominant_pct >= DOMINANT_COLOR_PCT_LIMIT:
        reasons.append(f"{dominant_pct:.0f}% of the image is a single flat color")
    if uniform_row_pct >= UNIFORM_ROW_PCT_LIMIT:
        reasons.append(f"{uniform_row_pct:.0f}% of rows contain no variation")
    if content_top_pct >= CONTENT_TOP_PCT_LIMIT:
        reasons.append(f"no content rendered in the top {content_top_pct:.0f}% of the viewport")

    quality = ScreenshotQuality(
        status="degraded" if reasons else "ok",
        dominant_color_pct=round(dominant_pct, 1),
        uniform_row_pct=round(uniform_row_pct, 1),
        content_top_pct=round(content_top_pct, 1),
        reason=(
            "The page did not finish rendering before capture: " + ", ".join(reasons) + "."
            if reasons
            else None
        ),
    )
    logger.info(
        "render_quality.measured status=%s dominant=%.1f%% uniform_rows=%.1f%% content_top=%.1f%%",
        quality.status, dominant_pct, uniform_row_pct, content_top_pct,
    )
    return quality
