"""Chart images for the PDF report — same two charts as the dashboard's ChartsSection.tsx
(category-score bars, issues-by-severity donut), rendered server-side with matplotlib since a
PDF can only embed a static image, not an interactive recharts component.

Uses the non-interactive Agg backend (no display needed) and returns PNG bytes ready for
ReportLab's Image flowable.
"""

from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

import os  # noqa: E402

from pdf_theme import FONT_DIR, MPL  # noqa: E402

_CATEGORY_LABELS = {
    "accessibility": "Accessibility",
    "seo": "SEO",
    "performance": "Performance",
    "copy": "Copy",
    "visual": "Visual",
}
_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]

_FONTS_LOADED = False


def _load_chart_fonts() -> str:
    """Registers Instrument Sans (regular + bold, so matplotlib's fontweight="bold" resolves to
    the real bold face instead of silently substituting) with matplotlib's font manager, so
    chart labels match the report's body typeface instead of matplotlib's default. Returns the
    family name to use, falling back to a generic sans-serif if the font files are missing."""
    global _FONTS_LOADED
    family = "Instrument Sans"
    regular = os.path.join(FONT_DIR, "InstrumentSans-Regular.ttf")
    bold = os.path.join(FONT_DIR, "InstrumentSans-Bold.ttf")
    if not _FONTS_LOADED and os.path.exists(regular) and os.path.exists(bold):
        fm.fontManager.addfont(regular)
        fm.fontManager.addfont(bold)
        _FONTS_LOADED = True
    return family if _FONTS_LOADED else "DejaVu Sans"


def _score_color(score: float | None) -> str:
    if score is None:
        return MPL["score_unknown"]
    if score >= 90:
        return MPL["score_good"]
    if score >= 50:
        return MPL["score_needs_work"]
    return MPL["score_poor"]


def render_category_score_chart(category_scores: dict[str, float | None]) -> bytes:
    """Horizontal bar chart of the 5 category scores, 0-100, colored by score band."""
    family = _load_chart_fonts()
    labels = [_CATEGORY_LABELS.get(key, key.title()) for key in category_scores]
    scores = [value if value is not None else 0 for value in category_scores.values()]
    bar_colors = [_score_color(value) for value in category_scores.values()]

    fig, ax = plt.subplots(figsize=(6.4, 2.6), dpi=200)
    fig.patch.set_facecolor(MPL["cream"])
    ax.set_facecolor(MPL["cream"])

    y_pos = range(len(labels))
    ax.barh(y_pos, scores, color=bar_colors, height=0.6, zorder=3)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(labels, fontsize=10, color=MPL["ink"], fontfamily=family)
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.tick_params(axis="x", labelsize=8, colors=MPL["muted_fg"])
    ax.grid(axis="x", color=MPL["border"], linewidth=0.8, zorder=0)
    for spine in ax.spines.values():
        spine.set_visible(False)

    for y, value, raw in zip(y_pos, scores, category_scores.values()):
        text = "N/A" if raw is None else f"{value:.0f}"
        ax.text(value + 2, y, text, va="center", fontsize=9, color=MPL["ink"], fontfamily=family, fontweight="bold")

    fig.tight_layout(pad=1.0)
    return _fig_to_png(fig)


def render_severity_donut_chart(issue_counts: dict[str, int]) -> bytes | None:
    """Donut chart of issue counts by severity. Returns None if there are no issues at all,
    so the caller can skip embedding an empty/meaningless chart."""
    family = _load_chart_fonts()
    present = [(severity, issue_counts.get(severity, 0)) for severity in _SEVERITY_ORDER]
    present = [(severity, count) for severity, count in present if count > 0]
    if not present:
        return None

    labels = [severity.capitalize() for severity, _ in present]
    values = [count for _, count in present]
    donut_colors = [MPL[severity] for severity, _ in present]

    fig, ax = plt.subplots(figsize=(4.6, 3.4), dpi=200)
    fig.patch.set_facecolor(MPL["cream"])
    wedges, _ = ax.pie(
        values,
        colors=donut_colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": MPL["cream"], "linewidth": 2},
    )
    ax.set_aspect("equal")
    total = sum(values)
    ax.text(0, 0.08, str(total), ha="center", va="center", fontsize=20, color=MPL["ink"], fontfamily=family, fontweight="bold")
    ax.text(0, -0.18, "issues", ha="center", va="center", fontsize=9, color=MPL["muted_fg"], fontfamily=family)

    legend_labels = [f"{label} ({count})" for label, count in zip(labels, values)]
    ax.legend(
        wedges,
        legend_labels,
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        frameon=False,
        fontsize=9,
        labelcolor=MPL["ink"],
    )
    fig.tight_layout(pad=1.0)
    return _fig_to_png(fig)


def _fig_to_png(fig) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    return buffer.getvalue()
