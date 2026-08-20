"""Unit tests for screenshot render-quality detection. No browser needed."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from render_quality import analyze_render_quality


def png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def blank_capture(width: int = 640, height: int = 450, content_from: float = 0.82) -> bytes:
    """A capture shaped like the real failure: flat background, content only at the bottom.

    Modelled on an actual nike.com viewport capture that came back 71% a single
    color with nothing rendered above 82% of the height — which the pipeline
    then described as a well-composed hero section.
    """
    image = Image.new("RGB", (width, height), (245, 245, 245))
    for y in range(int(height * content_from), height):
        for x in range(0, width, 2):
            image.putpixel((x, y), ((x * 7) % 255, (y * 5) % 255, 90))
    return png_bytes(image)


def real_capture(width: int = 640, height: int = 450) -> bytes:
    """A page with a normal amount of structure: varied content top to bottom."""
    image = Image.new("RGB", (width, height), (255, 255, 255))
    for y in range(height):
        for x in range(0, width, 2):
            image.putpixel((x, y), ((x * 3 + y) % 255, (y * 7) % 255, (x + y) % 255))
    return png_bytes(image)


class TestDegradedDetection:
    def test_blank_hero_capture_is_degraded(self):
        quality = analyze_render_quality(blank_capture())

        assert quality.status == "degraded"
        assert quality.is_degraded
        assert quality.dominant_color_pct > 60
        assert quality.uniform_row_pct > 60
        assert quality.content_top_pct > 50

    def test_degraded_capture_explains_itself(self):
        quality = analyze_render_quality(blank_capture())

        # The reason travels into the report, so it has to read as an
        # explanation rather than a threshold dump.
        assert quality.reason is not None
        assert "did not finish rendering" in quality.reason
        assert "%" in quality.reason

    def test_entirely_blank_capture_is_degraded(self):
        quality = analyze_render_quality(png_bytes(Image.new("RGB", (320, 240), (255, 255, 255))))

        assert quality.status == "degraded"
        assert quality.dominant_color_pct == pytest.approx(100.0)
        assert quality.content_top_pct == pytest.approx(100.0)


class TestHealthyCaptures:
    def test_content_bearing_capture_is_ok(self):
        quality = analyze_render_quality(real_capture())

        assert quality.status == "ok"
        assert not quality.is_degraded
        assert quality.reason is None

    def test_generous_whitespace_is_not_flagged(self):
        """A clean, airy design must not be mistaken for a failed render."""
        image = Image.new("RGB", (640, 450), (255, 255, 255))
        # Content bands across the page with real whitespace between them —
        # roughly half the rows carry something.
        for band_start in range(10, 450, 40):
            for y in range(band_start, min(band_start + 22, 450)):
                for x in range(40, 600, 2):
                    image.putpixel((x, y), ((x * 5) % 255, 40, (y * 3) % 255))

        quality = analyze_render_quality(png_bytes(image))

        assert quality.status == "ok"


class TestFailureModes:
    def test_undecodable_bytes_are_unknown_not_degraded(self):
        """An unreadable image is an unknown, not a verdict about the page."""
        quality = analyze_render_quality(b"this is not a png")

        assert quality.status == "unknown"
        assert not quality.is_degraded

    def test_empty_bytes_are_unknown(self):
        quality = analyze_render_quality(b"")

        assert quality.status == "unknown"
