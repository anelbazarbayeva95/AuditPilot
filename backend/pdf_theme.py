"""Brand theme for PDF report generation — colors and typography lifted from the dashboard's
own design tokens (frontend/src/index.css) so the PDF reads as the same product, not a generic
ReportLab default. Hex values for the oklch() tokens were computed once via the standard OKLab
conversion and hardcoded here since ReportLab has no oklch support.

Fonts: Syne (display/headings) and Instrument Sans (body) are the same Google Fonts families the
dashboard uses. Static weight instances live in assets/fonts/ (see assets/fonts/OFL-*.txt for
license) since ReportLab's TTFont can't select a weight axis out of a variable font.
"""

from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

# Font family names as registered with ReportLab — used as `fontName` in styles below.
DISPLAY_EXTRABOLD = "Syne-ExtraBold"
DISPLAY_BOLD = "Syne-Bold"
DISPLAY_SEMIBOLD = "Syne-SemiBold"
BODY = "Instrument-Regular"
BODY_MEDIUM = "Instrument-Medium"
BODY_SEMIBOLD = "Instrument-SemiBold"
BODY_BOLD = "Instrument-Bold"
MONO = "Courier"

_FONTS_REGISTERED = False


def register_fonts() -> None:
    """Registers the brand TTFs with ReportLab. Safe to call more than once (e.g. once per
    PDF build) — re-registering the same name is a harmless no-op in ReportLab."""
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    for name, filename in (
        (DISPLAY_EXTRABOLD, "Syne-ExtraBold.ttf"),
        (DISPLAY_BOLD, "Syne-Bold.ttf"),
        (DISPLAY_SEMIBOLD, "Syne-SemiBold.ttf"),
        (BODY, "InstrumentSans-Regular.ttf"),
        (BODY_MEDIUM, "InstrumentSans-Medium.ttf"),
        (BODY_SEMIBOLD, "InstrumentSans-SemiBold.ttf"),
        (BODY_BOLD, "InstrumentSans-Bold.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, filename)))
    _FONTS_REGISTERED = True


def _hex(value: str) -> colors.Color:
    return colors.HexColor(value)


# Base palette — matches frontend/src/index.css :root exactly where it's a plain hex value;
# oklch() tokens were converted with the standard OKLab->linear-sRGB->sRGB formula.
CREAM = _hex("#FAF9F5")  # --background
CARD = _hex("#FFFFFF")  # --card
INK = _hex("#16181D")  # --foreground / --ink
INK_MUTED = _hex("#8B8F86")  # --ink-muted (on dark)
MUTED_BG = _hex("#F4F4F1")  # --secondary / --muted
MUTED_FG = _hex("#726E66")  # --muted-foreground
BORDER = _hex("#E9E9E5")  # --border
LIME = _hex("#A9E44A")  # --primary, oklch(85% 0.19 128)
LIME_ON_DARK = _hex("#A9E44A")  # --status-good-on-dark (same token value)

# Severity colors — exact hex values from ChartsSection.tsx's SEVERITY_HEX (recharts needs
# literal hex too, so that's already the canonical conversion of the oklch severity tokens).
SEVERITY_COLORS = {
    "critical": _hex("#B63039"),  # --destructive
    "high": _hex("#B63039"),
    "medium": _hex("#EB8A00"),  # --warning
    "low": _hex("#726E66"),  # --muted-foreground
    "info": _hex("#A7A39A"),
}
SEVERITY_TEXT_ON_CHIP = {
    "critical": colors.white,
    "high": colors.white,
    "medium": INK,
    "low": colors.white,
    "info": INK,
}

# Score bands — exact hex values from ChartsSection.tsx's SCORE_BAND_HEX, plus the darker
# "text" variants from lib/score.ts / --status-good/needs-work/poor (legible on a light bg).
STATUS_GOOD = _hex("#3B7B00")
STATUS_GOOD_BAR = _hex("#A9E44A")
STATUS_NEEDS_WORK = _hex("#B76C00")
STATUS_NEEDS_WORK_BAR = _hex("#E38F00")
STATUS_POOR = _hex("#AC3037")
STATUS_POOR_BAR = _hex("#B63039")

QUICKFIX_BG = _hex("#E6FACF")  # --quickfix-bg
QUICKFIX_TEXT = _hex("#326402")  # --quickfix-text

# A very light red tint for critical/high finding cards — matches the dashboard's
# bg-destructive/[0.03] treatment (IssueItem.tsx) that gives elevated-severity cards a subtly
# different background from everything else, without competing with the severity chip itself.
ELEVATED_BG = _hex("#FDF6F5")

# Bright variants for legible text on the dark "ink" surface (--status-*-on-dark), used by the
# executive summary's overall-score tile, which mirrors the dashboard's dark "spotlight" panel.
STATUS_GOOD_ON_DARK = LIME
STATUS_NEEDS_WORK_ON_DARK = _hex("#E99B2A")
STATUS_POOR_ON_DARK = _hex("#EA6A6A")


def score_band(score: float | None) -> tuple[colors.Color, colors.Color, str]:
    """Returns (text_color, bar_color, label) for a 0-100 score, matching the dashboard's
    good/needs-work/poor bands (>=90 good, 50-89 needs work, <50 poor)."""
    if score is None:
        return MUTED_FG, BORDER, "N/A"
    if score >= 90:
        return STATUS_GOOD, STATUS_GOOD_BAR, "Good"
    if score >= 50:
        return STATUS_NEEDS_WORK, STATUS_NEEDS_WORK_BAR, "Needs work"
    return STATUS_POOR, STATUS_POOR_BAR, "Poor"


def score_band_on_dark(score: float | None) -> colors.Color:
    """The bright '-on-dark' text color for a score band, for use on the ink-colored score tile."""
    if score is None:
        return INK_MUTED
    if score >= 90:
        return STATUS_GOOD_ON_DARK
    if score >= 50:
        return STATUS_NEEDS_WORK_ON_DARK
    return STATUS_POOR_ON_DARK


# Matplotlib hex equivalents (matplotlib wants '#rrggbb' strings, not reportlab Color objects) —
# kept byte-for-byte identical to ChartsSection.tsx's SCORE_BAND_HEX/SEVERITY_HEX so the PDF's
# charts use the exact same colors as the dashboard's.
MPL = {
    "ink": "#16181D",
    "cream": "#FAF9F5",
    "muted_fg": "#726E66",
    "border": "#E9E9E5",
    "lime": "#A9E44A",
    "score_good": "#A9E44A",
    "score_needs_work": "#E38F00",
    "score_poor": "#B63039",
    "score_unknown": "#9CA3AF",
    "critical": "#B63039",
    "high": "#B63039",
    "medium": "#EB8A00",
    "low": "#726E66",
    "info": "#A7A39A",
}
